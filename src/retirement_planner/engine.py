"""
Core retirement planning engine.

Key design decisions:
- The engine supports two monetary conventions via ``MonetaryConvention``:
  * REAL (default): all simulation values are in constant (base-year)
    purchasing-power dollars; investment returns are real.
  * NOMINAL: all values are in year-of-production dollars; expenses,
    income, and returns inflate with the general price level.
- Tax brackets are always nominal (they come from tax_law.py as
  actual IRS values).  In REAL mode the engine temporarily converts
  real income to nominal before calling calculate_taxes() and converts
  the resulting tax back to real.
- Withdrawals follow a tax-efficient order: RMD → taxable → pre-tax → Roth.
- Taxes distinguish ordinary income, long-term capital gains, and tax-free.
"""
from __future__ import annotations
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import math
import warnings
import numpy as np
from dataclasses import dataclass, field
from enum import Enum

from .models import (
    Scenario, Person, Account, IncomeStream, Expense,
    Mortgage, Windfall, HousingEvent, RothConversion, RolloverEvent,
    Dependent, EconomicAssumptions, SocialSecurity, AgeEvent, TaxableIncome,
    AssetAllocation, GlidepathConfig, MonetaryConvention,
)

from .monetary import MonetaryPolicy
from .fixes import process_housing_event, process_roth_conversions, apply_medical_inflation
from .tax_lots import calculate_121_exclusion
from .projection.services import make_year_context, make_state
from .sim_integration import determine_annual_filing_status, calculate_401k_limit
from .tax_law import (
    TaxLawRegistry, FilingStatus,
    calculate_irmaa as tax_law_irmaa,
    calculate_aca_subsidy as tax_law_aca,
    calculate_estate_tax as tax_law_estate,
)


# ---------------------------------------------------------------------------
# IRS Uniform Lifetime Table (Publication 590-B, Table III)
# Used for RMD calculations starting at age 73 (SECURE 2.0 Act).
# Key: age → distribution period (divisor).
# Ages beyond the table use the last period minus 1 per year.
# ---------------------------------------------------------------------------
_UNIFIED_LIFETIME_TABLE: Dict[int, float] = {
    72: 27.4, 73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7,
    77: 22.9, 78: 22.0, 79: 21.1, 80: 20.2, 81: 19.4,
    82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2,
    87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5,
    92: 10.8, 93: 10.1, 94: 9.5, 95: 8.9, 96: 8.4,
    97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4, 101: 6.0,
    102: 5.6, 103: 5.2, 104: 4.9, 105: 4.6, 106: 4.3,
    107: 4.1, 108: 3.9, 109: 3.7, 110: 3.5, 111: 3.4,
    112: 3.3, 113: 3.1, 114: 3.0, 115: 2.9, 116: 2.8,
    117: 2.7, 118: 2.5, 119: 2.3, 120: 2.0,
}

RMD_START_AGE = 73  # SECURE 2.0 Act


def _year_active_fraction(start_date: date, end_date: date, year: int) -> float:
    """Fraction of *year* during which a dated stream is active.

    End dates are exclusive: a stream ending on Jan 1 of *year* is
    treated as ending on Dec 31 of the prior year (e.g. a 30-year
    mortgage taken in 2023 ends on 2053-01-01 and makes its last
    payment in 2052).

    Returns 1.0 for streams spanning the full year and 0.0 for streams
    inactive in *year*.
    """
    from datetime import timedelta
    effective_end = end_date
    if end_date.month == 1 and end_date.day == 1:
        effective_end = end_date - timedelta(days=1)
    if year < start_date.year or year > effective_end.year:
        return 0.0
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    days_in_year = (year_end - year_start).days + 1
    active_start = max(start_date, year_start)
    active_end = min(effective_end, year_end)
    if active_end < active_start:
        return 0.0
    active_days = (active_end - active_start).days + 1
    return active_days / days_in_year


def _rmd_divisor(age: int) -> float:
    """Return the IRS Uniform Lifetime Table divisor for *age*.

    For ages >= 120 that aren't in the table, use the last known
    divisor minus one per year beyond 120 (per IRS guidelines).
    """
    if age in _UNIFIED_LIFETIME_TABLE:
        return _UNIFIED_LIFETIME_TABLE[age]
    if age < RMD_START_AGE:
        return float('inf')  # No RMD required
    # Ages beyond the table
    last_divisor = _UNIFIED_LIFETIME_TABLE[max(_UNIFIED_LIFETIME_TABLE.keys())]
    years_past = age - max(_UNIFIED_LIFETIME_TABLE.keys())
    return max(last_divisor - years_past, 1.0)


# ---------------------------------------------------------------------------
# Withdrawal strategy
# ---------------------------------------------------------------------------
class WithdrawalStrategy(Enum):
    """Withdrawal strategy options for stress scenarios."""
    fixed = "fixed"
    guardrails = "guardrails"
    floor_ceiling = "floor_ceiling"
    percent_of_portfolio = "percent_of_portfolio"
    dynamic = "dynamic"


# ---------------------------------------------------------------------------
# Withdrawal engine
# ---------------------------------------------------------------------------
@dataclass
class CostBasisTracker:
    """Tracks aggregate taxable-account basis.

    Core projections intentionally use aggregate basis, not synthetic shares.
    Default policy assumes initial taxable balance is entirely basis.
    """
    basis_by_account: Dict[str, float] = field(default_factory=dict)

    def get_basis(self, account_id: str, default: float = 0.0) -> float:
        return self.basis_by_account.get(account_id, default)

    def set_basis(self, account_id: str, value: float):
        self.basis_by_account[account_id] = value

    def debit_basis(self, account_id: str, amount: float) -> float:
        """Reduce basis by *amount* (clamped to 0). Returns actual reduction."""
        current = self.basis_by_account.get(account_id, 0.0)
        reduction = min(current, amount)
        self.basis_by_account[account_id] = current - reduction
        return reduction


@dataclass
class WithdrawalResult:
    """Details of a single withdrawal from one account."""
    account_id: str
    account_type: str      # "pre_tax", "taxable", "roth"
    amount: float          # Gross withdrawal
    tax_treatment: str     # "ordinary", "capital_gains", "tax_free"
    taxable_amount: float  # Amount subject to tax (could be less than amount)
    capital_gain: float    # Realized capital gain from this withdrawal


class WithdrawalEngine:
    """Manages tax-efficient withdrawals from investment accounts.

    Withdrawal priority (when covering a shortfall):
      1. RMD from pre-tax accounts (age 73+, forced)
      2. Taxable brokerage accounts (favorable LTCG treatment)
      3. Pre-tax accounts (401k, traditional IRA)
      4. Roth accounts (last resort — tax-free but depletes runway)

    Each withdrawal returns a ``WithdrawalResult`` that records the
    tax treatment so the engine can build a ``TaxableIncome`` object.
    """

    def __init__(self, accounts: Dict[str, Account],
                 cost_basis: CostBasisTracker):
        self.accounts = accounts
        self.cost_basis = cost_basis
        self._withdrawals: List[WithdrawalResult] = []

    @property
    def withdrawals(self) -> List[WithdrawalResult]:
        return list(self._withdrawals)

    def clear(self):
        """Reset withdrawals for a new year."""
        self._withdrawals = []

    # ------------------------------------------------------------------
    # RMD calculation
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_rmd(account_balance: float, age: int) -> float:
        """Calculate Required Minimum Distribution for a pre-tax account.

        RMDs begin at age 73 (SECURE 2.0 Act).  Returns 0 if the
        account holder is under 73 or has a zero/negative balance.
        """
        if age < RMD_START_AGE or account_balance <= 0:
            return 0.0
        divisor = _rmd_divisor(age)
        return account_balance / divisor

    # ------------------------------------------------------------------
    # Tax-efficient withdrawal ordering
    # ------------------------------------------------------------------
    def calculate_withdrawal_needed(
        self,
        year: int,
        expenses: float,
        income: float,
        ss_income: float = 0.0,
    ) -> float:
        """How much must be withdrawn from accounts to cover the gap.

        Positive return means a shortfall that must be funded from
        investment accounts.  Negative means surplus (excess goes
        to taxable brokerage or is saved).
        """
        return max(0.0, expenses - income)

    def execute_withdrawals(
        self,
        needed: float,
        balances: Dict[str, float],
        year: int,
        primary_age: int,
        spouse_age: int,
        sale_date: Optional[date] = None,
    ) -> List[WithdrawalResult]:
        """Withdraw from accounts in tax-efficient order until *needed* is met.

        Returns a list of ``WithdrawalResult`` objects.  Side-effects
        update *balances* and ``cost_basis`` in place.
        """
        self.clear()
        remaining = needed
        # --- Step 1: Force RMDs from pre-tax accounts (age 73+) ---
        remaining = self._withdraw_rmds(balances, primary_age, spouse_age, remaining)

        # --- Step 2: Taxable brokerage ---
        remaining = self._withdraw_from_category(
            balances, remaining,
            category_filter=lambda a: a.tax_treatment == "taxable",
            tax_treatment="capital_gains",
            sale_date=sale_date,
        )

        # --- Step 3: Pre-tax (401k, traditional IRA) ---
        remaining = self._withdraw_from_category(
            balances, remaining,
            category_filter=lambda a: a.tax_treatment == "pre_tax",
            tax_treatment="ordinary",
        )

        # --- Step 4: Roth (last resort) ---
        remaining = self._withdraw_from_category(
            balances, remaining,
            category_filter=lambda a: a.tax_treatment == "roth",
            tax_treatment="tax_free",
        )

        return self._withdrawals

    # ------------------------------------------------------------------
    # Internal withdrawal helpers
    # ------------------------------------------------------------------
    def _withdraw_rmds(
        self,
        balances: Dict[str, float],
        primary_age: int,
        spouse_age: int,
        remaining: float,
    ) -> float:
        """Force RMDs from all pre-tax accounts, return remaining shortfall.

        Calculate RMDs by owner, aggregating traditional IRA balances.
        Mandatory distributions are separate from spending need; surplus
        is reinvested into a liquid taxable or checking account.
        """
        # Phase 1: Calculate required RMD per account
        groups: Dict[tuple, List[Tuple[str, float]]] = {}
        for account_id, account in self.accounts.items():
            if account.tax_treatment != "pre_tax":
                continue
            balance = balances.get(account_id, 0.0)
            if balance <= 0:
                continue
            owner = (account.owner or "primary").lower()
            owner_age = spouse_age if owner == "spouse" else primary_age
            if owner_age < RMD_START_AGE:
                continue
            group = "ira" if account.account_type in {"trad_ira", "traditional_ira"} else account_id
            groups.setdefault((owner, group), []).append((account_id, balance))

        rmds: Dict[str, float] = {}
        for (owner, _group), members in groups.items():
            age = spouse_age if owner == "spouse" else primary_age
            total_balance = sum(balance for _, balance in members)
            total_rmd = self.calculate_rmd(total_balance, age)
            for aid, balance in members:
                if total_balance > 0 and total_rmd > 0:
                    rmds[aid] = total_rmd * balance / total_balance

        if not rmds:
            return remaining

        total_required = sum(rmds.values())

        # Phase 2: Cap each RMD at available balance
        capped = {}
        for aid, rmd in rmds.items():
            capped[aid] = min(rmd, balances.get(aid, 0.0))

        total_capped = sum(capped.values())

        # Phase 4: Execute withdrawals
        original_need = remaining
        for account_id, amount in capped.items():
            if amount <= 0:
                continue
            balance = balances[account_id]
            actual = min(amount, balance)
            gain = actual - self.cost_basis.debit_basis(account_id, actual)
            balances[account_id] = balance - actual
            self._withdrawals.append(WithdrawalResult(
                account_id=account_id,
                account_type=self.accounts[account_id].account_type,
                amount=actual,
                tax_treatment="ordinary",
                taxable_amount=actual,
                capital_gain=max(0.0, gain),
            ))
            remaining = max(0.0, remaining - actual)

        surplus = max(0.0, total_capped - original_need)
        if surplus > 0:
            destination = next((aid for aid, account in self.accounts.items()
                                if account.tax_treatment == "taxable" and account.liquid), None)
            if destination is None:
                destination = next((aid for aid, account in self.accounts.items()
                                    if account.account_type == "checking" and account.liquid), None)
            if destination is not None:
                balances[destination] = balances.get(destination, 0.0) + surplus
                self._withdrawals.append(WithdrawalResult(
                    account_id=destination,
                    account_type=self.accounts[destination].account_type,
                    amount=surplus,
                    tax_treatment="rmd_reinvested",
                    taxable_amount=0.0,
                    capital_gain=0.0,
                ))

        return remaining

    def _withdraw_from_category(
        self,
        balances: Dict[str, float],
        remaining: float,
        category_filter,
        tax_treatment: str,
        sale_date: Optional[date] = None,
    ) -> float:
        """Withdraw from accounts matching *category_filter* until remaining is 0."""
        for account_id, account in self.accounts.items():
            if remaining <= 0:
                break
            if not category_filter(account):
                continue
            # Never liquidate illiquid assets (e.g. real estate) to fund
            # ordinary spending — those require a housing event.
            if (account.account_type == "real_estate"
                    or not account.liquid):
                continue
            balance = balances.get(account_id, 0.0)
            if balance <= 0:
                continue

            withdraw = min(remaining, balance)

            # For taxable accounts, compute capital gain portion
            capital_gain = 0.0
            taxable_amount = 0.0
            if tax_treatment == "capital_gains":
                basis_used = self.cost_basis.debit_basis(account_id, withdraw)
                capital_gain = withdraw - basis_used
                taxable_amount = capital_gain
            elif tax_treatment == "ordinary":
                taxable_amount = withdraw
            # tax_free: taxable_amount stays 0

            balances[account_id] = balance - withdraw
            remaining = max(0.0, remaining - withdraw)

            self._withdrawals.append(WithdrawalResult(
                account_id=account_id,
                account_type=account.account_type,
                amount=withdraw,
                tax_treatment=tax_treatment,
                taxable_amount=taxable_amount,
                capital_gain=capital_gain,
            ))
        return remaining

    def contribute(
        self,
        balances: Dict[str, float],
        available_savings: float,
    ) -> Dict[str, float]:
        """Distribute surplus savings into accounts by contribution priority.

        Accounts are funded in ascending ``contribution_priority`` order
        (accounts with priority 0 are skipped).  Each account receives
        ``min(remaining_savings, annual_contribution_cap - already_contributed)``
        where a cap of 0 means unlimited.  Employer match is computed
        separately and added on top of the employee contribution — it is
        not deducted from available savings.

        Returns dict of {account_id: total_contribution} for logging.
        """
        contributions: Dict[str, float] = {}
        if available_savings <= 0:
            return contributions

        eligible = sorted(
            (a for a in self.accounts.values() if a.contribution_priority > 0),
            key=lambda a: a.contribution_priority,
        )

        remaining = available_savings
        for account in eligible:
            if remaining <= 0:
                break

            if account.annual_contribution_cap > 0:
                employee = min(remaining, account.annual_contribution_cap)
            else:
                employee = remaining  # Unlimited — receives the remainder
            if employee <= 0:
                continue
            remaining -= employee

            # Employer match: separate calc on top of employee contribution
            match = 0.0
            if account.employer_match > 0 and account.employer_match_limit > 0:
                matchable = min(employee, account.employer_match_limit)
                match = matchable * account.employer_match
            elif account.employer_match > 0:
                match = employee * account.employer_match

            total = employee + match
            account_id = account.id
            balances[account_id] = balances.get(account_id, 0.0) + total
            contributions[account_id] = total
            # Increase cost basis for taxable accounts (contributions are basis)
            if account.tax_treatment == "taxable":
                current_basis = self.cost_basis.get_basis(account_id, 0.0)
                self.cost_basis.set_basis(account_id, current_basis + total)


        return contributions


# ---------------------------------------------------------------------------
# Tax calculation — delegates to tax_law.py for versioned brackets
# ---------------------------------------------------------------------------
# ACA (Affordable Care Act) subsidy constants — 2024 base year
# ---------------------------------------------------------------------------
_FPL_BASE_FAMILY_OF_4 = 31_200      # 2024 Federal Poverty Level for family of 4
_FPL_PER_ADDITIONAL_PERSON = 5_380  # Additional per person beyond 4

# Applicable percentage of household income used to calculate
# the "expected contribution" toward the second-lowest silver plan.
_ACA_APPLICABLE_PERCENTAGES: List[Tuple[float, float]] = [
    (1.33, 0.021),
    (1.50, 0.030),
    (2.00, 0.040),
    (2.50, 0.063),
    (3.00, 0.081),
    (4.00, 0.097),
]
_ACA_FPL_CLIFF_RATIO = 4.0  # No subsidy above 400% FPL (2024 baseline)

# Second-lowest silver plan monthly premiums (2024 approximations)
_ACA_SILVER_PREMIUMS: Dict[str, Dict[int, float]] = {
    "CA": {1: 800, 2: 1600, 3: 1800, 4: 2000, 5: 2200},
    "_default": {1: 800, 2: 1600, 3: 1800, 4: 2000, 5: 2200},
}

# ---------------------------------------------------------------------------
# Federal estate tax constants — 2024 base year
# ---------------------------------------------------------------------------
_ESTATE_TAX_RATE = 0.40
_ESTATE_EXEMPTION_SINGLE = 13_610_000   # $13.61M per person (2024)
_ESTATE_EXEMPTION_MFJ = 27_220_000      # $27.22M combined (2024)


# ---------------------------------------------------------------------------
# Engine-backed tax evaluator — implements TaxEvaluator protocol
# ---------------------------------------------------------------------------
class EngineTaxEvaluator:
    """Concrete evaluator that uses the engine's tax, ACA, and IRMAA methods.

    This replaces the optimizer's proxy scoring with real calculations.
    Instantiated by the engine and passed to the optimizer via config.
    """

    def __init__(self, engine: "RetirementPlanner"):
        self._engine = engine

    def evaluate(
        self,
        decision: "YearDecision",
        year: int,
        age: int,
        ordinary_income_baseline: float,
        family_size: int = 2,
    ) -> "TaxEvaluation":
        """Compute tax, ACA, and IRMAA costs for a candidate decision."""
        from .optimizer import TaxEvaluation
        from .models import TaxableIncome

        decision.compute_totals()

        # Additional ordinary income from this decision (pre-tax withdrawals + Roth conversions)
        additional_ordinary = (
            sum(decision.pretax_withdrawals.values())
            + sum(decision.roth_conversions.values())
        )

        # Total ordinary income = baseline + optimizer additions
        total_ordinary = ordinary_income_baseline + additional_ordinary

        # Build TaxableIncome for engine calculation
        ti = TaxableIncome(
            ordinary=total_ordinary,
            capital_gains=decision.realized_ltcg,
            tax_free=sum(decision.roth_withdrawals.values()),
            total=total_ordinary + decision.realized_ltcg,
        )

        # Baseline tax (without this decision)
        baseline_ti = TaxableIncome(
            ordinary=ordinary_income_baseline,
            capital_gains=0.0,
            tax_free=0.0,
            total=ordinary_income_baseline,
        )

        inflation_rate = 0.0
        years_from_base = max(0, year - self._engine.start_year)
        try:
            rates = self._engine.scenario.economic.get_rate("mean")
            inflation_rate = rates.get("general_inflation", 0.0)
        except (AttributeError, KeyError):
            pass

        # Tax with decision
        tax_with = self._engine.calculate_taxes(
            year, ti, "mean",
            inflation_rate=inflation_rate,
            years_from_base=years_from_base,
        )
        # Baseline tax (no optimizer action)
        tax_without = self._engine.calculate_taxes(
            year, baseline_ti, "mean",
            inflation_rate=inflation_rate,
            years_from_base=years_from_base,
        )
        marginal_tax = max(0.0, tax_with - tax_without)

        # ACA subsidy (pre-Medicare only)
        aca_subsidy = 0.0
        if age < 65:
            aca_subsidy = self._engine.calculate_aca_subsidy(
                total_ordinary, family_size, self._engine.scenario.state,
            )

        # IRMAA (2-year lookback, Medicare age 65+)
        irmaa_cost = 0.0
        if age >= 65:
            # Use current year MAGI as proxy for 2-year-ago MAGI
            irmaa_cost = self._engine.calculate_irmaa(total_ordinary, age)

        # NIIT
        niit = 0.0
        if decision.realized_ltcg > 0:
            magi = total_ordinary + decision.realized_ltcg
            niit = self._engine.calculate_niit(decision.realized_ltcg, magi)

        # Combined score: tax + IRMAA + NIIT - ACA subsidy preserved
        # (negative ACA subsidy means lost subsidy = cost)
        total_cost = marginal_tax + irmaa_cost + niit - aca_subsidy

        return TaxEvaluation(
            total_tax=marginal_tax,
            aca_subsidy=aca_subsidy,
            irmaa_cost=irmaa_cost,
            niit=niit,
            total_cost=total_cost,
        )


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------
class RetirementPlanner:
    """
    Main retirement planning engine.

    Projects year-by-year cash flow, account balances, taxes,
    and runs Monte Carlo simulations to calculate success rates.
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.accounts = {a.id: a for a in scenario.accounts}
        self.start_year = datetime.now().year
        # When set by MonteCarloEngine for historical simulations, the planner
        # uses this list of sequential returns instead of random gaussian draws.
        self._historical_return_override: Optional[List[float]] = None
    @classmethod
    def from_config(cls, config_path: str) -> 'RetirementPlanner':
        """Load planner from JSON config file."""
        import json
        from .config.validation import validate_config
        try:
            with open(config_path) as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Invalid JSON in config file '{config_path}': {e.msg}",
                e.doc, e.pos)

        validation = validate_config(config)
        validation.raise_for_errors()
        
        # Parse config into Scenario
        # This is a simplified parser - full implementation would handle all fields
        from datetime import date
        
        primary_cfg = config["primary"]
        spouse_cfg = config["spouse"]
        for who, pcfg in (("primary", primary_cfg), ("spouse", spouse_cfg)):
            if "social_security_benefit" in pcfg or "ss_claiming_age" in pcfg:
                warnings.warn(
                    f"{who}.social_security_benefit / ss_claiming_age are "
                    f"legacy fields not honored by the engine — configure "
                    f"'social_security' (benefits at 67 + claiming age) "
                    f"instead; the settings are ignored.", UserWarning)
        primary = Person(
            name=primary_cfg["name"],
            birth_date=date.fromisoformat(primary_cfg["birth_date"]),
            retirement_date=date.fromisoformat(primary_cfg["retirement_date"]),
            longevity_age=primary_cfg.get("longevity_age", 90),
        )
        
        spouse = Person(
            name=spouse_cfg["name"],
            birth_date=date.fromisoformat(spouse_cfg["birth_date"]),
            retirement_date=date.fromisoformat(spouse_cfg["retirement_date"]),
            longevity_age=spouse_cfg.get("longevity_age", 90),
        )
        
        # Parse accounts
        accounts = []
        for acc_config in config.get("accounts", []):
            for dead in ("growth_rate_optimistic", "growth_rate_pessimistic",
                         "asset_class"):
                if dead in acc_config:
                    warnings.warn(
                        f"account '{acc_config.get('id')}': '{dead}' is not "
                        f"honored by the engine (use 'economic' rates or "
                        f"'equity_pct'); the setting is ignored.",
                        UserWarning)
            accounts.append(Account(
                id=acc_config["id"],
                name=acc_config["name"],
                account_type=acc_config["type"],
                tax_treatment=acc_config.get("tax_treatment", "taxable"),
                balance=acc_config["balance"],
                growth_rate=acc_config.get("growth_rate"),
                monthly_contribution=acc_config.get("monthly_contribution", 0.0),
                employer_match=acc_config.get("employer_match", 0.0),
                employer_match_limit=acc_config.get("employer_match_limit", 0.0),
                contribution_priority=acc_config.get("contribution_priority", 0),
                annual_contribution_cap=acc_config.get("annual_contribution_cap", 0.0),
                expense_ratio=acc_config.get("expense_ratio", 0.0),
                equity_pct=acc_config.get("equity_pct"),
                owner=acc_config.get("owner", "primary"),
                # Vehicles depreciate by default; everything else stays
                # liquid/stable unless the config says otherwise.
                is_depreciating=acc_config.get(
                    "is_depreciating",
                    acc_config["type"] == "vehicle"),
                liquid=acc_config.get("liquid", True),
            ))

        # Resolve savings allocation priorities:
        #   1. Explicit per-account contribution_priority wins.
        #   2. Otherwise, position in top-level savings_order (1-based).
        #   3. Otherwise, legacy monthly_contribution > 0 → appended after
        #      savings_order entries, with annual cap = 12 × monthly amount.
        savings_order = config.get("savings_order", [])
        raw_accounts = {a["id"]: a for a in config.get("accounts", [])}
        accounts_by_id = {a.id: a for a in accounts}
        for position, acc_id in enumerate(savings_order, start=1):
            acct = accounts_by_id.get(acc_id)
            if acct is None:
                continue
            if "contribution_priority" not in raw_accounts.get(acc_id, {}):
                acct.contribution_priority = position
        next_priority = len(savings_order) + 1
        for acct in accounts:
            if acct.contribution_priority == 0 and acct.monthly_contribution > 0:
                acct.contribution_priority = next_priority
                next_priority += 1
                if "annual_contribution_cap" not in raw_accounts.get(acct.id, {}):
                    acct.annual_contribution_cap = acct.monthly_contribution * 12
        
        # Parse economic assumptions
        econ_config = config.get("economic", {})
        economic = EconomicAssumptions(
            general_inflation=econ_config.get("inflation", 0.0254),
            general_inflation_optimistic=econ_config.get("inflation_optimistic", 0.0203),
            general_inflation_pessimistic=econ_config.get("inflation_pessimistic", 0.0305),
            medical_inflation=econ_config.get("medical_inflation", 0.0336),
            medical_inflation_optimistic=econ_config.get("medical_inflation_optimistic", 0.0269),
            medical_inflation_pessimistic=econ_config.get("medical_inflation_pessimistic", 0.0403),
            housing_appreciation=econ_config.get("housing_appreciation", 0.044),
            housing_appreciation_optimistic=econ_config.get("housing_appreciation_optimistic", 0.0528),
            housing_appreciation_pessimistic=econ_config.get("housing_appreciation_pessimistic", 0.0352),
            # Capital market assumptions (Phase 2.4)
            equity_real_return=econ_config.get("equity_real_return", 0.06),
            equity_real_return_optimistic=econ_config.get("equity_real_return_optimistic", 0.08),
            equity_real_return_pessimistic=econ_config.get("equity_real_return_pessimistic", 0.04),
            bond_real_return=econ_config.get("bond_real_return", 0.025),
            bond_real_return_optimistic=econ_config.get("bond_real_return_optimistic", 0.035),
            bond_real_return_pessimistic=econ_config.get("bond_real_return_pessimistic", 0.015),
        )

        # Parse income streams
        from .models import RSUGrant, RefresherPolicy, Bonus, EquityComp
        income_streams = []
        for ic in config.get("income_streams", []):
            # Parse optional base_salary
            base_salary = None
            if "base_salary" in ic:
                base_salary = ic["base_salary"]

            # Parse optional bonus
            bonus = None
            if "bonus" in ic:
                bc = ic["bonus"]
                bonus = Bonus(
                    annual=bc.get("annual", 0),
                    growth_rate=bc.get("growth_rate", 0),
                    payment_month=bc.get("payment_month", 3),
                )

            # Parse optional equity
            equity = None
            if ic.get("equity"):
                ec = ic["equity"]
                grants = []
                for g in ec.get("grants", []):
                    grants.append(RSUGrant(
                        id=g["id"],
                        grant_date=date.fromisoformat(g["grant_date"]),
                        total_shares=g["total_shares"],
                        vesting_pattern=g["vesting_pattern"],
                        cliff_shares=g.get("cliff_shares", 0),
                        periodic_shares=g.get("periodic_shares", 0),
                        cliff_date=date.fromisoformat(g["cliff_date"]) if g.get("cliff_date") else None,
                        cliff_replaces_first_vest=g.get("cliff_replaces_first_vest", False),
                        status=g.get("status", "active"),
                    ))
                refresher = None
                if "refreshers" in ec and ec["refreshers"]:
                    rp = ec["refreshers"]
                    refresher = RefresherPolicy(
                        annual_shares=rp["annual_shares"],
                        grant_month=rp["grant_month"],
                        vesting_pattern=rp["vesting_pattern"],
                        vesting_delay_months=rp.get("vesting_delay_months", 3),
                        start_year=rp["start_year"],
                        end_year=rp["end_year"],
                        growth_rate=rp.get("growth_rate", 0),
                    )
                equity = EquityComp(
                    ticker=ec.get("ticker", ""),
                    current_price=ec.get("current_price", 0),
                    price_source=ec.get("price_source", "manual"),
                    grants=grants,
                    refreshers=refresher,
                    # Vesting stops when employment ends: default the
                    # equity end date to the income stream's end date
                    # when the equity block does not override it.
                    end_date=(date.fromisoformat(ec["end_date"])
                              if ec.get("end_date")
                              else date.fromisoformat(ic["end_date"])
                              if ic.get("end_date")
                              else None),
                    sell_to_cover=ec.get("sell_to_cover", True),
                    is_taxable=ec.get("is_taxable", True),
                    goes_to_account=ec.get("goes_to_account", ""),
                )

            # Compute monthly_amount from base_salary if provided (legacy compat)
            monthly_amount = ic.get("monthly_amount", 0)
            if base_salary and monthly_amount == 0:
                monthly_amount = base_salary["annual"] / 12

            if ic.get("is_ss") or ic.get("is_passive"):
                warnings.warn(
                    f"income_stream '{ic.get('id')}': 'is_ss'/'is_passive' "
                    f"are legacy fields not honored by the engine (all "
                    f"streams are treated as ordinary income); ignored.",
                    UserWarning)

            income_streams.append(IncomeStream(
                id=ic["id"],
                name=ic["name"],
                owner=ic["owner"],
                monthly_amount=monthly_amount,
                start_date=date.fromisoformat(ic["start_date"]),
                end_date=date.fromisoformat(ic["end_date"]),
                growth_rate=ic.get("growth_rate", 0.0),
                is_w2=ic.get("is_w2", True),
                is_passive=ic.get("is_passive", False),
                is_ss=ic.get("is_ss", False),
                goes_to_account=ic.get("goes_to_account", ""),
                base_salary=base_salary,
                bonus=bonus,
                equity=equity,
            ))

        # Parse expenses
        expenses = []
        for ec in config.get("expenses", []):
            if ec.get("growth_rate") and ec.get("real_growth_rate"):
                warnings.warn(
                    f"expense '{ec.get('id')}': both 'growth_rate' and "
                    f"'real_growth_rate' set — 'real_growth_rate' wins.",
                    UserWarning)
            if ec.get("min_reduction"):
                warnings.warn(
                    f"expense '{ec.get('id')}': 'min_reduction' (stress-"
                    f"testing) is not wired to any simulation path; "
                    f"ignored.", UserWarning)
            one_time_date = ec.get("one_time_date")
            expenses.append(Expense(
                id=ec["id"],
                name=ec["name"],
                monthly_amount=ec["monthly_amount"],
                start_date=date.fromisoformat(ec["start_date"]),
                end_date=date.fromisoformat(ec["end_date"]),
                growth_rate=ec.get("growth_rate", 0.0),
                real_growth_rate=ec.get("real_growth_rate", 0.0),
                is_one_time=ec.get("is_one_time", False),
                one_time_amount=ec.get("one_time_amount", 0.0),
                one_time_date=date.fromisoformat(one_time_date) if one_time_date else None,
                category=ec.get("category", "general"),
                is_must_spend=ec.get("is_must_spend", True),
                min_reduction=ec.get("min_reduction", 0.0),
            ))

        # Parse mortgages
        mortgages = []
        for mc in config.get("mortgages", []):
            mortgages.append(Mortgage(
                id=mc["id"],
                name=mc["name"],
                property_id=mc["property_id"],
                balance=mc["balance"],
                interest_rate=mc["interest_rate"],
                monthly_payment=mc["monthly_payment"],
                start_date=date.fromisoformat(mc["start_date"]),
                end_date=date.fromisoformat(mc["end_date"]),
                is_tax_deductible=mc.get("is_tax_deductible", True),
            ))

        # Parse windfalls
        windfalls = []
        for wf in config.get("windfalls", []):
            windfalls.append(Windfall(
                id=wf["id"],
                name=wf["name"],
                amount=wf["amount"],
                date=date.fromisoformat(wf["date"]),
                goes_to_account=wf.get("goes_to_account", ""),
                is_taxable=wf.get("is_taxable", True),
                source_account=wf.get("source_account", ""),
            ))

        # Parse housing events
        housing_events = []
        for he in config.get("housing_events", []):
            housing_events.append(HousingEvent(
                id=he["id"],
                name=he["name"],
                event_date=date.fromisoformat(he["event_date"]),
                sale_price=he.get("sale_price", 0.0),
                purchase_price=he.get("purchase_price", 0.0),
                down_payment=he.get("down_payment", 0.0),
                mortgage_amount=he.get("mortgage_amount", 0.0),
                mortgage_rate=he.get("mortgage_rate", 0.05),
                mortgage_term_years=he.get("mortgage_term_years", 30),
                property_id=he.get("property_id", ""),
                goes_to_account=he.get("goes_to_account", "joint_brokerage"),
                funding_account=he.get("funding_account", "joint_brokerage"),
                new_mortgage_id=he.get("new_mortgage_id", ""),
            ))

        # Parse Roth conversions
        roth_conversions = []
        for rc in config.get("roth_conversions", []):
            roth_conversions.append(RothConversion(
                id=rc["id"],
                name=rc["name"],
                source_account=rc["source_account"],
                target_account=rc["target_account"],
                start_date=date.fromisoformat(rc["start_date"]),
                end_date=date.fromisoformat(rc["end_date"]),
                annual_amount=rc["annual_amount"],
            ))

        # Parse rollover events (401k -> IRA at retirement)
        rollover_events = []
        for ro in config.get("rollover_events", []):
            rollover_events.append(RolloverEvent(
                id=ro["id"],
                name=ro["name"],
                event_date=date.fromisoformat(ro["event_date"]),
                source_account=ro["source_account"],
                target_account=ro["target_account"],
            ))

        # Parse dependents (children drive ACA family size dynamically)
        dependents = []
        for dep in config.get("dependents", []):
            dependents.append(Dependent(
                name=dep.get("name", "Child"),
                birth_date=date.fromisoformat(dep["birth_date"]),
            ))

        # Parse age events
        age_events = []
        for ae in config.get("age_events", []):
            age_events.append(AgeEvent(
                trigger_age=ae["trigger_age"],
                expense_id=ae["expense_id"],
                new_monthly_amount=ae.get("new_monthly_amount"),
                duration_years=ae.get("duration_years", -1),
            ))

        # Parse social security
        ss_config = config.get("social_security", {})
        if "family_size" in config:
            warnings.warn(
                "'family_size' is superseded by 'dependents' (ACA family "
                "size is now dynamic: spouses + children under 26); the "
                "setting is ignored.", UserWarning)
        social_security = SocialSecurity(
            primary_benefit_at_67=ss_config.get("primary_benefit_at_67", 3000),
            primary_claiming_age=ss_config.get("primary_claiming_age", 67),
            spouse_benefit_at_67=ss_config.get("spouse_benefit_at_67", 2500),
            spouse_claiming_age=ss_config.get("spouse_claiming_age", 67),
            # Single source for SS COLA: economic.ss_cola feeds
            # SocialSecurity.cola_rate unless overridden explicitly.
            cola_rate=ss_config.get("cola_rate", economic.ss_cola),
        )

        # Parse glidepath config
        glidepath = None
        gp_config = config.get("glidepath")
        if gp_config:
            glidepath = GlidepathConfig(
                equity_by_age={
                    int(k): v for k, v in gp_config.get("equity_by_age", {}).items()
                },
                pre_retirement_years=gp_config.get("pre_retirement_years", 5),
                post_retirement_years=gp_config.get("post_retirement_years", 5),
                tent_equity_pct=gp_config.get("tent_equity_pct", 0.30),
                tent_ramp_years=gp_config.get("tent_ramp_years", 3),
            )

        scenario = Scenario(
            name=config.get("name", "Default Scenario"),
            description=config.get("description", ""),
            primary=primary,
            spouse=spouse,
            economic=economic,
            accounts=accounts,
            income_streams=income_streams,
            expenses=expenses,
            mortgages=mortgages,
            windfalls=windfalls,
            housing_events=housing_events,
            roth_conversions=roth_conversions,
            rollover_events=rollover_events,
            dependents=dependents,
            age_events=age_events,
            social_security=social_security,
            glidepath=glidepath,
            legacy_goal=config.get("legacy_goal", 2_000_000),
            state=config.get("state", "CA"),
            savings_order=savings_order,
            withdrawal_strategy=config.get("withdrawal_strategy", "fixed"),
            withdrawal_rate=config.get("withdrawal_rate", 0.04),
        )
        
        return cls(scenario)

    # ------------------------------------------------------------------
    # Equity glidepath / asset allocation
    # ------------------------------------------------------------------
    def get_equity_allocation(self, age: int) -> AssetAllocation:
        """Return age-appropriate asset allocation based on glidepath.

        When no glidepath is configured, returns 100% equity (backward
        compatible with existing behavior).

        The bond tent widens the bond allocation around retirement:
        - Within [retirement - pre, retirement + post]: use tent_equity_pct
        - After the tent: gradually ramp back to normal glidepath
        """
        gp = self.scenario.glidepath
        if gp is None:
            return AssetAllocation(equity_pct=1.0, bond_pct=0.0)

        # --- Normal glidepath interpolation ---
        normal_eq = self._interpolate_glidepath(gp.equity_by_age, age)

        # --- Bond tent adjustment ---
        ret_age = (self.scenario.primary.retirement_date.year
                   - self.scenario.primary.birth_date.year)
        tent_start = ret_age - gp.pre_retirement_years
        tent_end = ret_age + gp.post_retirement_years

        if age < tent_start:
            # Before tent: normal glidepath
            equity = normal_eq
        elif age <= tent_end:
            # During tent: use tent_equity_pct
            equity = gp.tent_equity_pct
        else:
            # After tent: ramp back from tent_equity_pct to normal
            years_past_tent = age - tent_end
            if years_past_tent >= gp.tent_ramp_years:
                equity = normal_eq
            else:
                # Linear interpolation from tent value to glidepath value
                t = years_past_tent / gp.tent_ramp_years
                equity = gp.tent_equity_pct + t * (normal_eq - gp.tent_equity_pct)

        equity = max(0.0, min(1.0, equity))
        bond = 1.0 - equity
        return AssetAllocation(equity_pct=equity, bond_pct=bond)

    @staticmethod
    def _interpolate_glidepath(
        equity_by_age: Dict[int, float],
        age: int,
    ) -> float:
        """Linearly interpolate equity percentage between age anchors."""
        if not equity_by_age:
            return 1.0

        ages = sorted(equity_by_age.keys())

        # Clamp to range
        if age <= ages[0]:
            return equity_by_age[ages[0]]
        if age >= ages[-1]:
            return equity_by_age[ages[-1]]

        # Find bracketing ages
        for i in range(len(ages) - 1):
            if ages[i] <= age <= ages[i + 1]:
                a0, a1 = ages[i], ages[i + 1]
                e0, e1 = equity_by_age[a0], equity_by_age[a1]
                t = (age - a0) / (a1 - a0) if a1 != a0 else 0
                return e0 + t * (e1 - e0)

        return equity_by_age[ages[-1]]

    def get_growth_rate_for_allocation(
        self,
        account: Account,
        allocation: AssetAllocation,
    ) -> float:
        """Compute net growth rate for an account given an allocation.

        Returns: equity_rate * equity_pct + bond_rate * bond_pct,
        minus the account's expense ratio.

        Uses scenario-level capital market assumptions by default.
        If account.growth_rate is set, it overrides the equity rate
        for backward compatibility with legacy configs.
        """
        rates = self.scenario.economic.get_rate("mean")
        inflation = rates["general_inflation"]

        # Scenario-level capital market assumptions
        bond_rate = rates["bond_real_return"]
        equity_rate = rates["equity_real_return"]

        # Per-account override: if growth_rate is set, use it as equity rate
        # (backward compatibility with configs that specify a single blended rate)
        if account.growth_rate is not None and account.growth_rate != 0:
            equity_rate = account.growth_rate

        if self.scenario.monetary_convention == MonetaryConvention.NOMINAL:
            bond_rate = (1.0 + bond_rate) * (1.0 + inflation) - 1.0
            equity_rate = (1.0 + equity_rate) * (1.0 + inflation) - 1.0

        gross_rate = (equity_rate * allocation.equity_pct
                      + bond_rate * allocation.bond_pct)
        net_rate = gross_rate - account.expense_ratio
        return net_rate

    def _account_growth_rate(self, account: Account, year: int,
                             rates: Dict) -> float:
        """Deterministic annual growth rate for an account (no volatility).

        Mirrors the Monte Carlo growth step: allocation rates are already
        convention-adjusted inside get_growth_rate_for_allocation; the
        non-allocation rates (real estate, depreciating assets, cash) are
        real and get converted exactly once.
        """
        policy = MonetaryPolicy(
            convention=self.scenario.monetary_convention,
            base_year=self.start_year,
            inflation=rates["general_inflation"],
        )
        if account.account_type == "real_estate":
            rate = rates["housing_appreciation"]
        elif account.is_depreciating:
            rate = -0.04
        elif account.growth_rate == 0:
            rate = 0
        else:
            owner_age = self._account_owner_age(account, year)
            allocation = self.get_equity_allocation(owner_age)
            if account.equity_pct is not None:
                allocation = AssetAllocation(
                    account.equity_pct, 1.0 - account.equity_pct)
            return self.get_growth_rate_for_allocation(account, allocation)
        return policy.portfolio_return_to_convention(
            rate, rates["general_inflation"])

    def get_account_balance(self, account_id: str, year: int,
                            scenario: str = "mean") -> float:
        """Get projected account balance for a given year (deterministic)."""
        account = self.accounts.get(account_id)
        if not account:
            return 0.0

        years = year - self.start_year
        rates = self.scenario.economic.get_rate(scenario)
        rate = self._account_growth_rate(account, year, rates)
        return account.project_balance(years, rate)

    def _dependents_under_26(self, year: int) -> int:
        """Number of configured dependents under 26 in *year*.

        Children can stay on a parent's ACA plan until 26, so they count
        toward the household family size for subsidy calculation.
        """
        count = 0
        for dep in self.scenario.dependents:
            age = year - dep.birth_date.year
            if 0 <= age < 26:
                count += 1
        return count

    def _account_owner_age(self, account: Account, year: int) -> int:
        owner = (account.owner or "primary").lower()
        spouse_name = self.scenario.spouse.name.lower()
        person = self.scenario.spouse if owner in {"spouse", spouse_name} else self.scenario.primary
        return year - person.birth_date.year

    def calculate_net_worth(self, year: int, scenario: str = "mean",
                            mortgage_balances: Optional[Dict[str, float]] = None) -> Dict:
        """Calculate net worth at a given year.

        When *mortgage_balances* is provided (deterministic projections),
        outstanding mortgage balances are counted as liabilities so the
        result matches the Monte Carlo path's net-worth convention.
        """
        total_assets = 0
        total_liabilities = 0
        account_balances = {}

        for account_id, account in self.accounts.items():
            balance = self.get_account_balance(account_id, year, scenario)
            account_balances[account_id] = balance

            if balance >= 0:
                total_assets += balance
            else:
                total_liabilities += abs(balance)

        if mortgage_balances:
            total_liabilities += sum(
                b for b in mortgage_balances.values() if b > 0)

        return {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "net_worth": total_assets - total_liabilities,
            "accounts": account_balances,
        }

    # ------------------------------------------------------------------
    # Income
    # ------------------------------------------------------------------
    def _medical_expenses_base(self, year: int) -> float:
        """Current-year medical-category expense total (with age events)."""
        mods = self.calculate_age_events(year)
        total = 0.0
        for exp in self.scenario.expenses:
            if exp.is_one_time or exp.category != "medical":
                continue
            monthly = mods.get(exp.id, exp.monthly_amount)
            total += (monthly * 12
                      * _year_active_fraction(exp.start_date, exp.end_date, year))
        return total

    def _medical_inflation_extra(self, year: int, excess_rate: float) -> float:
        """Extra healthcare cost from medical inflation exceeding general.

        Age events step healthcare costs up (e.g. 65 -> Medicare costs,
        75 -> LTC).  The excess rate compounds only from the start of the
        CURRENT cost level (expense start or the latest age-event
        trigger), not from the simulation start — otherwise a $120K LTC
        step at 75 would compound for 50+ years.
        """
        if excess_rate <= 0 or year <= self.start_year:
            return 0.0
        mods = self.calculate_age_events(year)
        total_extra = 0.0
        for exp in self.scenario.expenses:
            if exp.is_one_time or exp.category != "medical":
                continue
            monthly = mods.get(exp.id, exp.monthly_amount)
            base = monthly * 12 * _year_active_fraction(
                exp.start_date, exp.end_date, year)
            if base <= 0:
                continue
            # Level start = the latest age-event trigger year (or expense
            # start).  Trigger age is relative to the younger person.
            younger_birth = max(
                self.scenario.primary.birth_date.year,
                self.scenario.spouse.birth_date.year,
            )
            latest_trigger = 0
            for ev in self.scenario.age_events:
                if ev.expense_id == exp.id:
                    trigger_year = younger_birth + ev.trigger_age
                    if trigger_year <= year:
                        latest_trigger = max(latest_trigger, trigger_year)
            level_start = max(exp.start_date.year, latest_trigger)
            years = year - level_start
            if years > 0:
                total_extra += base * ((1.0 + excess_rate) ** years - 1.0)
        return total_extra

    def calculate_annual_income(self, year: int,
                                scenario: str = "mean") -> Dict:
        """Calculate total income for a year.

        Supports two modes per stream:
        - Legacy: monthly_amount × 12 × growth (unchanged)
        - Enhanced: base_salary + bonus + equity (new fields)
        """
        total_income = 0
        income_by_source = {}

        for stream in self.scenario.income_streams:
            fraction = _year_active_fraction(
                stream.start_date, stream.end_date, year)
            if fraction <= 0:
                continue
            years_active = year - stream.start_date.year

            if stream.base_salary or stream.equity:
                # Enhanced mode: base + bonus + equity
                stream_income = 0

                # Base salary (prorated for partial start/end years)
                if stream.base_salary:
                    base = stream.base_salary["annual"]
                    growth = stream.base_salary.get("growth_rate", 0)
                    stream_income += (base * (1 + growth) ** years_active
                                      * fraction)

                    # Bonus (annual lump sum) — skip if the stream ends
                    # before the payment month in the final year
                    if stream.bonus and stream.bonus.annual > 0:
                        end_month = stream.end_date.month
                        if (year < stream.end_date.year
                                or stream.bonus.payment_month <= end_month):
                            bonus_growth = stream.bonus.growth_rate
                            stream_income += (stream.bonus.annual
                                              * (1 + bonus_growth) ** years_active
                                              * fraction)

                    # RSU equity — day-exact via equity.end_date
                    # (defaulted to the stream end date at parse time)
                    if stream.equity and stream.equity.ticker:
                        rsu_income = self.calculate_annual_rsu_income(
                            year, stream.equity)
                        stream_income += rsu_income
                        if rsu_income > 0:
                            income_by_source[f"{stream.name} — RSU"] = rsu_income

                    total_income += stream_income
                    income_by_source[stream.name] = stream_income
                else:
                    # Enhanced stream with equity only (no base salary)
                    if stream.equity and stream.equity.ticker:
                        rsu_income = self.calculate_annual_rsu_income(
                            year, stream.equity)
                        stream_income += rsu_income
                        if rsu_income > 0:
                            income_by_source[f"{stream.name} — RSU"] = rsu_income
                    total_income += stream_income
            else:
                # Legacy mode: flat monthly amount with growth
                amount = (stream.monthly_amount * 12
                          * (1 + stream.growth_rate) ** years_active
                          * fraction)
                total_income += amount
                income_by_source[stream.name] = amount

        return {"total": total_income, "by_source": income_by_source}

    # ------------------------------------------------------------------
    # Equity Compensation — RSU vesting math (stateless)
    # ------------------------------------------------------------------
    def calculate_annual_rsu_income(self, year: int, equity) -> float:
        """Calculate total RSU income for a year from all active grants + refreshers.

        Args:
            year: Calendar year.
            equity: EquityComp instance with grants and optional refresher policy.

        Returns:
            Total RSU income in dollars (shares × current_price).
        """
        from .models import RSUGrant, EquityComp
        total_shares = 0.0

        # 1. Explicit grants
        for grant in equity.grants:
            if equity.end_date and grant.grant_date > equity.end_date:
                continue  # grant cancelled
            shares = self._vested_shares_in_year(grant, year, equity.end_date)
            total_shares += shares

        # 2. Auto-generated refreshers
        if equity.refreshers:
            policy = equity.refreshers
            for grant_year in range(policy.start_year, min(year, policy.end_year) + 1):
                if equity.end_date and date(grant_year, policy.grant_month, 1) > equity.end_date:
                    continue
                grant_shares = policy.annual_shares * (1 + policy.growth_rate) ** (grant_year - policy.start_year)
                grant_date = date(grant_year, policy.grant_month, 1)
                # Determine periodic shares based on vesting pattern
                if policy.vesting_pattern == "quarterly":
                    periodic = grant_shares / 4  # shares per quarter
                    total = grant_shares * 4     # 4 years × annual_shares
                elif policy.vesting_pattern == "monthly":
                    periodic = grant_shares / 12
                    total = grant_shares * 4
                else:
                    periodic = grant_shares
                    total = grant_shares * 4
                synthetic_grant = RSUGrant(
                    id=f"grant_{grant_year}",
                    grant_date=grant_date,
                    total_shares=total,
                    vesting_pattern=policy.vesting_pattern,
                    periodic_shares=periodic,
                    status="forecasted" if year > grant_year + 1 else "active"
                )
                total_shares += self._vested_shares_in_year(synthetic_grant, year, equity.end_date)

        return total_shares * equity.current_price

    def _vested_shares_in_year(self, grant, year: int, end_date=None) -> float:
        """How many shares from this grant vest in a given year. Stateless."""
        if end_date and date(year, 12, 31) > end_date:
            return 0  # job ended — no more vests

        if grant.vesting_pattern == "cliff_quarterly":
            return self._cliff_quarterly_vests(grant, year)
        elif grant.vesting_pattern == "quarterly":
            return self._quarterly_vests(grant, year)
        elif grant.vesting_pattern == "monthly":
            return self._monthly_vests(grant, year)
        return 0

    def _cliff_quarterly_vests(self, grant, year: int) -> float:
        """Cliff + quarterly vesting. Handles cliff_replaces_first_vest.

        Stateless: computes cumulative vests up to year and year-1, returns delta.
        """
        cumulative_now = self._cliff_quarterly_cumulative(grant, year)
        cumulative_prev = self._cliff_quarterly_cumulative(grant, year - 1)
        return min(cumulative_now - cumulative_prev, grant.total_shares - cumulative_prev)

    def _cliff_quarterly_cumulative(self, grant, year: int) -> float:
        """Cumulative shares vested through end of `year`."""
        if grant.cliff_date is None or year < grant.cliff_date.year:
            return 0.0

        total = grant.cliff_shares  # cliff always vests

        if grant.cliff_replaces_first_vest:
            # Cliff replaces Q1: Q2,Q3,Q4 in cliff year, then 4/yr after
            years_after_cliff = max(0, year - grant.cliff_date.year)
            if years_after_cliff == 0:
                total += grant.periodic_shares * 3  # Q2, Q3, Q4
            else:
                total += grant.periodic_shares * 3  # Q2-Q4 of cliff year
                total += grant.periodic_shares * 4 * years_after_cliff
        else:
            # Cliff only in cliff year, quarterly starts year after
            years_after_cliff = max(0, year - grant.cliff_date.year)
            total += grant.periodic_shares * 4 * years_after_cliff

        return min(total, grant.total_shares)

    def _quarterly_vests(self, grant, year: int) -> float:
        """Quarterly vesting, no cliff. Stateless cumulative approach."""
        cumulative_now = self._quarterly_cumulative(grant, year)
        cumulative_prev = self._quarterly_cumulative(grant, year - 1)
        return min(cumulative_now - cumulative_prev, grant.total_shares - cumulative_prev)

    def _quarterly_cumulative(self, grant, year: int) -> float:
        """Cumulative shares vested through end of `year`, capped at total_shares."""
        if year < grant.grant_date.year:
            return 0.0

        if year == grant.grant_date.year:
            months_active = 13 - grant.grant_date.month
            quarters = months_active // 3
            return min(grant.periodic_shares * quarters, grant.total_shares)

        years_after_grant = year - grant.grant_date.year
        first_year_quarters = (13 - grant.grant_date.month) // 3
        total_quarters = first_year_quarters + 4 * years_after_grant
        # Cap: 4-year vest = max 16 quarters
        total_quarters = min(total_quarters, 16)
        return min(grant.periodic_shares * total_quarters, grant.total_shares)

    def _monthly_vests(self, grant, year: int) -> float:
        """Monthly vesting. Stateless cumulative approach."""
        cumulative_now = self._monthly_cumulative(grant, year)
        cumulative_prev = self._monthly_cumulative(grant, year - 1)
        return min(cumulative_now - cumulative_prev, grant.total_shares - cumulative_prev)

    def _monthly_cumulative(self, grant, year: int) -> float:
        """Cumulative shares vested through end of `year`, capped at total_shares."""
        if year < grant.grant_date.year:
            return 0.0

        if year == grant.grant_date.year:
            months_active = 13 - grant.grant_date.month
            return min(grant.periodic_shares * months_active, grant.total_shares)

        years_after_grant = year - grant.grant_date.year
        first_year_months = 13 - grant.grant_date.month
        total_months = first_year_months + 12 * years_after_grant
        # Cap: 4-year vest = max 48 months
        total_months = min(total_months, 48)
        return min(grant.periodic_shares * total_months, grant.total_shares)

    # ------------------------------------------------------------------
    # Expenses  — FIX: no inflation multiplier (returns are real)
    # ------------------------------------------------------------------
    def calculate_annual_expenses(
        self,
        year: int,
        scenario: str = "mean",
        stress_level: float = 0.0,
        mortgage_balances: Optional[Dict[str, float]] = None,
        event_mortgage_terms: Optional[Dict[str, tuple]] = None,
    ) -> Dict:
        """Calculate total expenses for a year.

        Since investment returns are REAL (inflation-adjusted), all
        dollar amounts in the simulation are in constant purchasing-
        power terms.  Expenses are therefore **not** escalated by
        inflation — they already represent the real cost each year.

        Args:
            year: Calendar year.
            scenario: Economic scenario (for age-event overrides only).
            stress_level: 0.0 = normal, 1.0 = max stress.
            mortgage_balances: Optional dict of mortgage.id -> remaining
                balance.  When provided, each year's payment is amortized:
                interest = balance * rate, principal = payment - interest,
                and the dict is updated in place.  Mortgages paid down to
                zero stop generating expenses.  When None, payments are
                modeled flat (legacy behavior).
        """
        total_expenses = 0
        expenses_by_category = {}
        expense_mods = self.calculate_age_events(year)

        for expense in self.scenario.expenses:
            if expense.is_one_time:
                if expense.one_time_date and expense.one_time_date.year == year:
                    total_expenses += expense.one_time_amount
                    expenses_by_category[expense.name] = expense.one_time_amount
            else:
                if expense.start_date.year <= year <= expense.end_date.year:
                    monthly = expense.monthly_amount

                    # Apply age-event overrides
                    if expense.id in expense_mods:
                        monthly = expense_mods[expense.id]

                    # NO inflation multiplier — returns are real, so
                    # expenses stay flat in real terms.
                    amount = monthly * 12
                    # Explicit real growth (e.g. childcare costs outpace
                    # general inflation).  real_growth_rate wins; the
                    # legacy growth_rate is treated as REAL growth too
                    # (matching Account.growth_rate semantics).
                    growth_rate = (
                        expense.real_growth_rate
                        if expense.real_growth_rate
                        else expense.growth_rate)
                    if growth_rate:
                        amount *= (1 + growth_rate) ** (
                            year - expense.start_date.year)
                    # Prorate partial start/end years (end-exclusive)
                    amount *= _year_active_fraction(
                        expense.start_date, expense.end_date, year)

                    # Apply stress reduction for discretionary expenses
                    if stress_level > 0 and not expense.is_must_spend:
                        reduction = expense.min_reduction * stress_level
                        amount *= (1.0 - reduction)

                    total_expenses += amount
                    expenses_by_category[expense.name] = amount

        # Add mortgage payments (amortized when balances are tracked).
        # Mortgages amortize monthly (US convention: nominal APR / 12);
        # annual-compounding on the year-start balance diverges from real
        # schedules and leaves a phantom residual liability.
        for mortgage in self.scenario.mortgages:
            if mortgage.start_date.year <= year <= mortgage.end_date.year:
                if mortgage_balances is not None:
                    balance = mortgage_balances.get(mortgage.id, 0.0)
                    if balance <= 0:
                        continue  # Paid off — no more payments
                    fraction = _year_active_fraction(
                        mortgage.start_date, mortgage.end_date, year)
                    amount = 0.0
                    monthly_rate = mortgage.interest_rate / 12
                    months = round(12 * fraction)
                    for _ in range(months):
                        if balance <= 0:
                            break
                        interest = balance * monthly_rate
                        payment = min(
                            mortgage.monthly_payment, balance + interest)
                        balance -= payment - interest
                        amount += payment
                    mortgage_balances[mortgage.id] = max(0.0, balance)
                else:
                    amount = mortgage.monthly_payment * 12 * _year_active_fraction(
                        mortgage.start_date, mortgage.end_date, year)
                total_expenses += amount
                expenses_by_category[f"Mortgage - {mortgage.name}"] = amount

        # Mortgages created by housing events (not in scenario.mortgages):
        # amortize from the event date using the payment computed at
        # creation.  Terms stored as (rate, monthly_payment, start_date).
        if mortgage_balances is not None and event_mortgage_terms:
            static_ids = {m.id for m in self.scenario.mortgages}
            for mort_id, balance in list(mortgage_balances.items()):
                if mort_id in static_ids or balance <= 0:
                    continue
                terms = event_mortgage_terms.get(mort_id)
                if terms is None:
                    continue  # liability tracked, payment terms unknown
                rate, payment, start_date = terms
                if year < start_date.year:
                    continue
                months = 12
                if year == start_date.year:
                    # payments begin the month after the event
                    months = 12 - start_date.month
                amount = 0.0
                monthly_rate = rate / 12
                for _ in range(months):
                    if balance <= 0:
                        break
                    interest = balance * monthly_rate
                    pmt = min(payment, balance + interest)
                    balance -= pmt - interest
                    amount += pmt
                mortgage_balances[mort_id] = max(0.0, balance)
                if amount > 0:
                    total_expenses += amount
                    expenses_by_category[f"Mortgage - {mort_id}"] = amount

        return {"total": total_expenses, "by_category": expenses_by_category}

    def calculate_stress_expenses(
        self,
        year: int,
        stress_level: float = 0.0,
        scenario: str = "mean",
    ) -> Dict:
        """Calculate expenses under a stress scenario."""
        return self.calculate_annual_expenses(year, scenario, stress_level)

    def calculate_age_events(self, year: int) -> Dict[str, float]:
        """Return modified monthly amounts triggered by age events."""
        primary_age = year - self.scenario.primary.birth_date.year
        spouse_age = year - self.scenario.spouse.birth_date.year
        younger_age = min(primary_age, spouse_age)

        mods: Dict[str, float] = {}
        for event in self.scenario.age_events:
            if younger_age < event.trigger_age:
                continue

            if event.duration_years > 0:
                years_since_trigger = younger_age - event.trigger_age
                if years_since_trigger >= event.duration_years:
                    continue

            if event.new_monthly_amount is not None:
                mods[event.expense_id] = event.new_monthly_amount
            else:
                for exp in self.scenario.expenses:
                    if exp.id == event.expense_id:
                        mods[event.expense_id] = exp.monthly_amount
                        break

        return mods

    # ------------------------------------------------------------------
    # Taxes  — uses TaxLawRegistry for versioned, year-aware brackets
    # ------------------------------------------------------------------
    def calculate_taxes(
        self,
        year: int,
        income: "TaxableIncome",
        scenario: str = "mean",
        inflation_rate: float = 0.0,
        years_from_base: int = 0,
        # New parameters for Phase 1c
        salt_paid: float = 0.0,
        charitable_deductions: float = 0.0,
        qcd_amount: float = 0.0,
        num_children: int = 0,
        age: float = 0.0,
        ira_balance: float = 0.0,
        charitably_inclined: bool = False,
        # Phase 1d: filing status override
        filing_status=None,
    ) -> float:
        """Calculate federal + CA state taxes using versioned tax law.

        Now includes: NIIT, AMT, SALT cap, QCD, child tax credit,
        and itemized vs standard deduction optimization.
        """
        from .tax_law import TaxLawRegistry, FilingStatus, bracket_tax

        # Get versioned tax law for this year
        if not hasattr(self, '_tax_registry'):
            self._tax_registry = TaxLawRegistry()
        law = self._tax_registry.law_for_year(
            year,
            fallback_inflation=inflation_rate if inflation_rate > 0 else 0.025,
        )

        # Determine filing status
        if filing_status is not None:
            status = filing_status
        else:
            status = FilingStatus.MFJ

        # ---- QCD reduces AGI before deductions ----
        from .tax_law import calculate_qcd
        actual_qcd = calculate_qcd(ira_balance, age, charitably_inclined, law)
        # QCD is excluded from AGI (not a deduction, just not counted as income)
        # For simplicity, we reduce ordinary income by QCD amount
        ordinary_for_tax = max(0.0, income.ordinary - actual_qcd)

        # ---- Standard vs itemized deduction ----
        standard_deduction = law.standard_deduction.get(status, 29_200)
        # SALT cap
        salt_cap = law.salt_cap if law.salt_cap is not None else float('inf')
        salt_deduction = min(salt_paid, salt_cap)
        itemized = salt_deduction + charitable_deductions
        deduction = max(standard_deduction, itemized)

        # ---- Federal ordinary income tax ----
        ordinary_after_deduction = max(0.0, ordinary_for_tax - deduction)
        fed_brackets = law.federal_brackets.get(status, [])
        federal_ordinary = bracket_tax(ordinary_after_deduction, fed_brackets)

        # ---- Federal long-term capital gains tax ----
        ltcg_taxable = income.capital_gains
        ltcg_brackets = law.ltcg_brackets.get(status, [])
        if ltcg_taxable > 0:
            remaining_ordinary = ordinary_after_deduction
            ltcg_tax = 0.0
            prev_threshold = 0.0
            for b in ltcg_brackets:
                if ltcg_taxable <= 0:
                    break
                bracket_width = b.upper - prev_threshold
                prev_threshold = b.upper
                ordinary_in_bracket = min(remaining_ordinary, bracket_width)
                remaining_ordinary -= ordinary_in_bracket
                available = bracket_width - ordinary_in_bracket
                if available <= 0:
                    continue
                taxed_here = min(ltcg_taxable, available)
                ltcg_tax += taxed_here * b.rate
                ltcg_taxable -= taxed_here
        else:
            ltcg_tax = 0.0

        federal_tax = federal_ordinary + ltcg_tax

        # ---- NIIT (Net Investment Income Tax) ----
        from .tax_law import calculate_niit
        magi = ordinary_for_tax + income.capital_gains
        niit = calculate_niit(income.capital_gains, magi, law, status)
        federal_tax += niit

        # ---- AMT (Alternative Minimum Tax) ----
        from .tax_law import calculate_amt
        amt = calculate_amt(federal_tax, ordinary_for_tax, income.capital_gains, law, status)
        federal_tax += amt

        # ---- Child Tax Credit ----
        from .tax_law import calculate_child_tax_credit
        ctc = calculate_child_tax_credit(num_children, magi, law, status)
        federal_tax = max(0.0, federal_tax - ctc)

        # ---- California state tax (all ordinary — CA taxes LTCG as ordinary) ----
        # Only CA has modeled brackets; other states pay no state income
        # tax in this engine (better than charging CA tax in TX).
        ca_tax = 0.0
        if str(getattr(self.scenario, "state", "CA")).upper() == "CA":
            ca_total = ordinary_for_tax + income.capital_gains
            ca_taxable = max(0.0, ca_total - deduction)  # CA uses same standard deduction
            ca_brackets = law.ca_brackets
            ca_tax = bracket_tax(ca_taxable, ca_brackets)

        return federal_tax + ca_tax

    # ------------------------------------------------------------------
    # IRMAA — Income-Related Monthly Adjustment Amount (Medicare surcharges)
    # ------------------------------------------------------------------
    # 2024 MFJ thresholds and per-person surcharges (monthly).
    # Current-year premiums are based on MAGI from 2 years prior.
    _IRMAA_PART_B_TIERS: List[Tuple[float, float]] = [
        (206_000, 0.0),
        (258_000, 70.0),
        (322_000, 175.0),
        (386_000, 380.0),
        (750_000, 484.0),
        (float('inf'), 587.0),
    ]
    _IRMAA_PART_D_TIERS: List[Tuple[float, float]] = [
        (206_000, 0.0),
        (258_000, 10.0),
        (322_000, 26.0),
        (386_000, 43.0),
        (750_000, 60.0),
        (float('inf'), 77.0),
    ]

    def calculate_irmaa(self, magi_2_years_ago: float, age: int) -> float:
        """Calculate annual IRMAA Medicare surcharges for a couple.

        Uses 2024 MFJ tiers.  Returns the total annual surcharge for
        two people (both Part B + Part D).  Returns 0 if age < 65.
        """
        if age < 65:
            return 0.0

        # Part B surcharge per person
        part_b = 0.0
        for threshold, surcharge in self._IRMAA_PART_B_TIERS:
            if magi_2_years_ago <= threshold:
                part_b = surcharge
                break

        # Part D surcharge per person
        part_d = 0.0
        for threshold, surcharge in self._IRMAA_PART_D_TIERS:
            if magi_2_years_ago <= threshold:
                part_d = surcharge
                break

        per_person_monthly = part_b + part_d
        # x2 for couple, x12 for annual
        return per_person_monthly * 2 * 12

    # ------------------------------------------------------------------
    # Social Security taxation
    # ------------------------------------------------------------------
    def calculate_ss_taxable(self, ss_benefits: float,
                             other_income: float) -> float:
        """Calculate the taxable portion of Social Security benefits.

        Uses 2024 MFJ thresholds:
          - provisional_income = other_income + 50% of SS benefits
          - provisional_income <= $32K  -> $0 taxable
          - provisional_income <= $44K  -> lesser of 50% of SS or
                                           50% of (provisional - $32K)
          - provisional_income >  $44K  -> lesser of 85% of SS or
                                           $6K + 85% of (provisional - $44K)

        Args:
            ss_benefits: Annual Social Security benefits received.
            other_income: All other income (wages, interest, etc.)
                          -- does NOT include SS itself.
        """
        if ss_benefits <= 0:
            return 0.0

        provisional = other_income + 0.5 * ss_benefits

        lower_threshold = 32_000.0
        upper_threshold = 44_000.0

        if provisional <= lower_threshold:
            return 0.0

        if provisional <= upper_threshold:
            # Tier 2: lesser of 50% of SS or 50% of (provisional - $32K)
            return min(0.5 * ss_benefits,
                       0.5 * (provisional - lower_threshold))

        # Tier 3: lesser of 85% of SS or $6K + 85% of (provisional - $44K)
        tier2_amount = 0.5 * (upper_threshold - lower_threshold)  # $6,000
        tier3_calc = tier2_amount + 0.85 * (provisional - upper_threshold)
        return min(0.85 * ss_benefits, tier3_calc)

    # ------------------------------------------------------------------
    # NIIT -- Net Investment Income Tax
    # ------------------------------------------------------------------
    def calculate_niit(self, investment_income: float, magi: float) -> float:
        """Calculate Net Investment Income Tax (3.8% surtax).

        Applies to net investment income when MAGI exceeds $250K (MFJ).
        Investment income includes capital gains, dividends, and interest.
        """
        niit_threshold = 250_000.0
        niit_rate = 0.038

        if magi <= niit_threshold or investment_income <= 0:
            return 0.0

        # Tax on lesser of net investment income or excess MAGI over threshold
        excess_magi = magi - niit_threshold
        taxable_investment = min(investment_income, excess_magi)
        return taxable_investment * niit_rate

    # ------------------------------------------------------------------
    # ACA (Affordable Care Act) subsidies — pre-Medicare (age < 65)
    # ------------------------------------------------------------------
    def calculate_aca_subsidy(
        self,
        income: float,
        family_size: int = 2,
        state: str = "CA",
    ) -> float:
        """Calculate annual ACA premium subsidy for pre-Medicare retirees.

        The subsidy equals the second-lowest silver plan premium minus
        the household's expected contribution (income × applicable
        percentage based on FPL tier).  No subsidy is available above
        400% FPL (ACA cliff, 2024 rules).

        Args:
            income: Household MAGI (modified adjusted gross income).
            family_size: Number of people in the household.
            state: Two-letter state code for silver plan premium lookup.

        Returns:
            Annual subsidy (>= 0).  Returns 0 when income exceeds the
            400% FPL cliff.
        """
        # Compute Federal Poverty Level for this family size
        additional = family_size - 4
        fpl = _FPL_BASE_FAMILY_OF_4 + _FPL_PER_ADDITIONAL_PERSON * additional

        # FPL ratio
        fpl_ratio = income / fpl if fpl > 0 else 0.0

        # Cliff check — no subsidy above 400% FPL
        if fpl_ratio >= _ACA_FPL_CLIFF_RATIO:
            return 0.0

        # Find applicable percentage from tier table
        applicable_pct = 0.0
        for upper, pct in _ACA_APPLICABLE_PERCENTAGES:
            if fpl_ratio <= upper:
                applicable_pct = pct
                break

        expected_contribution = income * applicable_pct

        # Silver plan premium (monthly → annual)
        premiums = _ACA_SILVER_PREMIUMS.get(
            state, _ACA_SILVER_PREMIUMS["_default"])
        capped_size = min(family_size, 5)
        monthly_premium = premiums.get(capped_size, premiums[5])
        annual_premium = monthly_premium * 12

        subsidy = max(0.0, annual_premium - expected_contribution)
        return subsidy

    # ------------------------------------------------------------------
    # Federal estate tax
    # ------------------------------------------------------------------
    def calculate_estate_tax(
        self,
        net_worth: float,
        filing_status: str = "MFJ",
        inflation_rate: float = 0.0,
        years_from_base: int = 0,
    ) -> float:
        """Calculate federal estate tax due at end of life.

        The exemption is indexed to inflation.  Tax is 40% on the
        excess above the exemption.

        Args:
            net_worth: Total estate value at time of death.
            filing_status: ``'MFJ'`` for married filing jointly, else single.
            inflation_rate: Annual inflation rate for exemption indexing.
            years_from_base: Years since the 2024 base year.

        Returns:
            Federal estate tax owed.
        """
        # The exemption is indexed to inflation (nominal dollars); the
        # estate value arrives in the active convention, so convert it
        # to nominal before comparing, then convert the tax back.
        from .tax_law import estate_tax_on_taxable
        idx = (1.0 + inflation_rate) ** years_from_base
        if filing_status == "MFJ":
            exemption = _ESTATE_EXEMPTION_MFJ * idx
        else:
            exemption = _ESTATE_EXEMPTION_SINGLE * idx

        estate_nominal = net_worth * idx
        if estate_nominal <= exemption:
            return 0.0

        tax_nominal = estate_tax_on_taxable(estate_nominal - exemption)
        return tax_nominal / idx if idx else tax_nominal

    # ------------------------------------------------------------------
    # Social Security
    # ------------------------------------------------------------------
    def calculate_social_security(self, year: int, person: Person) -> float:
        """Calculate Social Security benefit for a year."""
        age = year - person.birth_date.year
        ss = self.scenario.social_security

        if person.name == self.scenario.primary.name:
            claiming_age = ss.primary_claiming_age
            benefit_at_67 = ss.primary_benefit_at_67
        else:
            claiming_age = ss.spouse_claiming_age
            benefit_at_67 = ss.spouse_benefit_at_67

        if age < claiming_age:
            return 0.0

        years_since_claiming = age - claiming_age
        cola = ss.cola_rate
        monthly_benefit = benefit_at_67 * (1 + cola) ** years_since_claiming

        return monthly_benefit * 12

    def _is_retired(self, year: int, person: Person) -> bool:
        """Check if *person* has reached retirement date by *year*."""
        return year >= person.retirement_date.year

    # ------------------------------------------------------------------
    # Withdrawal strategy methods
    # ------------------------------------------------------------------
    def apply_guardrails(
        self,
        year: int,
        base_spending: float,
        portfolio_value: float,
        portfolio_peak: float,
    ) -> float:
        """Guardrails-based spending strategy.

        Adjusts spending within a floor/ceiling band around the base
        spending level.  If the portfolio drops >20% from its prior peak,
        spending is cut by 5% (down to floor).  If it rises >10% above
        peak, spending increases by 3% (up to ceiling).

        Args:
            year: Current calendar year.
            base_spending: This year's planned expenses
                (calculate_annual_expenses() total) — the spending anchor.
            portfolio_value: Current total portfolio value.
            portfolio_peak: Highest portfolio value seen so far.

        Returns:
            Adjusted spending amount.
        """
        scenario = self.scenario
        floor = base_spending * scenario.guardrail_floor_pct
        ceiling = base_spending * scenario.guardrail_ceiling_pct

        # Portfolio change from peak (as fraction)
        if portfolio_peak > 0:
            peak_change = (portfolio_value - portfolio_peak) / portfolio_peak
        else:
            peak_change = 0.0

        adjusted = base_spending

        if peak_change < -0.20:
            # Portfolio dropped >20% — cut spending by 5%
            adjusted = base_spending * 0.95
        elif peak_change > 0.10:
            # Portfolio grew >10% — allow 3% increase
            adjusted = base_spending * 1.03

        # Clamp to floor/ceiling
        adjusted = max(floor, min(ceiling, adjusted))
        return adjusted

    def apply_dynamic_spending(
        self,
        year: int,
        base_spending: float,
        portfolio_value: float,
        expenses: Dict,
    ) -> float:
        """Dynamic spending strategy based on portfolio health.

        Monitors the spending rate (spending / portfolio).  If above 5%,
        cuts discretionary expenses.  If below 3%, allows a 2% increase.

        Args:
            year: Current calendar year.
            base_spending: The baseline annual spending.
            portfolio_value: Current total portfolio value.
            expenses: Dict with 'total' and 'by_category' keys.

        Returns:
            Adjusted spending amount.
        """
        if portfolio_value <= 0:
            return base_spending

        spending_rate = base_spending / portfolio_value

        if spending_rate > 0.05:
            # Unsustainable — reduce spending by applying a 10% cut
            # (reduces discretionary as much as possible first)
            adjusted = base_spending * 0.90
        elif spending_rate < 0.03:
            # Conservative — allow a 2% bump
            adjusted = base_spending * 1.02
        else:
            adjusted = base_spending

        # Never go below floor (must-spend expenses)
        must_spend_total = 0.0
        for exp in self.scenario.expenses:
            if exp.is_must_spend and not exp.is_one_time:
                fraction = _year_active_fraction(
                    exp.start_date, exp.end_date, year)
                if fraction > 0:
                    must_spend_total += exp.monthly_amount * 12 * fraction
        adjusted = max(must_spend_total, adjusted)

        return adjusted

    def apply_percent_of_portfolio(
        self,
        year: int,
        portfolio_value: float,
        withdrawal_rate: float,
        floor_expenses: float,
    ) -> float:
        """Withdraw a fixed percentage of portfolio each year.

        The withdrawal is floored at minimum expenses (fixed costs
        like housing, food) so essential needs are always met.

        Args:
            year: Current calendar year.
            portfolio_value: Current total portfolio value.
            withdrawal_rate: Annual withdrawal rate (e.g., 0.04 = 4%).
            floor_expenses: Minimum expenses that must be covered.

        Returns:
            Adjusted spending amount.
        """
        if portfolio_value <= 0:
            return floor_expenses

        percent_withdrawal = portfolio_value * withdrawal_rate
        return max(floor_expenses, percent_withdrawal)

    def apply_floor_ceiling(
        self,
        year: int,
        base_spending: float,
        portfolio_value: float,
        floor: float,
        ceiling: float,
    ) -> float:
        """Floor/ceiling spending strategy.

        Hard floor: minimum expenses (sum of all is_must_spend=True expenses).
        Hard ceiling: maximum expenses (base + 20%).
        Spending adjusts within these bounds based on portfolio value.

        When portfolio is healthy (above 25x annual spending), allow
        spending near the ceiling.  When stressed (below 15x), cut
        toward the floor.  Otherwise, spend at the base level.

        Args:
            year: Current calendar year.
            base_spending: The baseline annual spending.
            portfolio_value: Current total portfolio value.
            floor: Hard minimum (must-spend expenses).
            ceiling: Hard maximum (base + 20%).

        Returns:
            Adjusted spending amount clamped to [floor, ceiling].
        """
        if base_spending <= 0 or portfolio_value <= 0:
            return floor

        # Portfolio coverage ratio (how many years of base spending)
        coverage = portfolio_value / base_spending

        if coverage >= 25.0:
            # Very healthy — spend near ceiling
            adjusted = ceiling
        elif coverage >= 20.0:
            # Healthy — allow 10% above base
            adjusted = base_spending * 1.10
        elif coverage >= 15.0:
            # Normal — spend base
            adjusted = base_spending
        elif coverage >= 10.0:
            # Stressed — reduce by 10%
            adjusted = base_spending * 0.90
        else:
            # Severely stressed — cut to floor
            adjusted = floor

        return max(floor, min(ceiling, adjusted))

    def apply_withdrawal_strategy(
        self,
        year: int,
        base_spending: float,
        portfolio_value: float,
        portfolio_peak: float,
        expenses: Dict,
    ) -> float:
        """Dispatcher: apply the configured withdrawal strategy.

        Args:
            year: Current calendar year.
            base_spending: This year's planned expenses from
                calculate_annual_expenses() — the spending anchor.
            portfolio_value: Current total portfolio value.
            portfolio_peak: High-water mark (for reporting only).
            expenses: Dict with 'total' and 'by_category' from expenses calculation.

        Returns:
            Adjusted annual spending amount.
        """
        strategy = getattr(self.scenario, 'withdrawal_strategy', 'fixed')

        # Compute planned portfolio: starting value adjusted for inflation
        # This is the Guyton-Klinger reference path, not a high-water mark
        years_from_start = year - self.start_year
        inflation = getattr(self.scenario, 'inflation_rate', 0.025)
        starting_portfolio = getattr(self, '_starting_portfolio', portfolio_value)
        planned_portfolio = starting_portfolio * ((1 + inflation) ** years_from_start)

        if strategy == 'fixed':
            return base_spending

        elif strategy == 'guardrails':
            return self.apply_guardrails(
                year, base_spending, portfolio_value, planned_portfolio,
            )

        elif strategy == 'dynamic':
            return self.apply_dynamic_spending(
                year, base_spending, portfolio_value, expenses,
            )

        elif strategy == 'percent_of_portfolio':
            # Compute floor expenses (must-spend items)
            floor = 0.0
            for exp in self.scenario.expenses:
                if exp.is_must_spend and not exp.is_one_time:
                    fraction = _year_active_fraction(
                        exp.start_date, exp.end_date, year)
                    if fraction > 0:
                        floor += exp.monthly_amount * 12 * fraction
            withdrawal_rate = getattr(self.scenario, 'withdrawal_rate', 0.04)
            return self.apply_percent_of_portfolio(
                year, portfolio_value, withdrawal_rate, floor,
            )

        elif strategy == 'floor_ceiling':
            # Compute floor (must-spend) and ceiling (base + 20%)
            floor = 0.0
            for exp in self.scenario.expenses:
                if exp.is_must_spend and not exp.is_one_time:
                    fraction = _year_active_fraction(
                        exp.start_date, exp.end_date, year)
                    if fraction > 0:
                        floor += exp.monthly_amount * 12 * fraction
            ceiling = base_spending * 1.20
            return self.apply_floor_ceiling(
                year, base_spending, portfolio_value, floor, ceiling,
            )

        else:
            # Unknown strategy — fall back to fixed
            return base_spending

    # ------------------------------------------------------------------
    # Monte Carlo single simulation  — REWRITE: withdrawals, contributions,
    # RMDs, proper tax handling
    # ------------------------------------------------------------------
    def run_single_simulation(
        self,
        scenario_name: str = "mean",
        return_volatility: float = 0.15,
        rng=None,
        collect_projections: bool = False,
    ) -> Dict:
        """Run a single year-by-year projection with proper cash flow.

        This method implements:
        1. Investment returns (with optional volatility for Monte Carlo).
        2. Employee contributions + employer match during working years.
        3. Income from wages, Social Security, and other streams.
        4. Tax calculation that separates ordinary, capital gains, and
           tax-free income.
        5. Tax-efficient withdrawals (RMD → taxable → pre-tax → Roth).
        6. Windfall events.

        With *collect_projections* the per-year rows (income, expenses,
        taxes, ACA subsidy, net worth) are returned under "projections"
        — used by the MC↔deterministic parity harness.
        """
        total_taxes = 0.0
        total_ss = 0.0
        total_contributions = 0.0
        total_aca_subsidy = 0.0
        total_estate_tax = 0.0
        peak_nw = 0.0
        out_of_savings_year = None
        projections = [] if collect_projections else None

        # Starting balances
        balances: Dict[str, float] = {}
        for account_id, account in self.accounts.items():
            balances[account_id] = account.balance

        # Track mortgage balances separately — amortized annually and
        # subtracted from net worth as liabilities.
        mortgage_balances: Dict[str, float] = {}
        for mortgage in self.scenario.mortgages:
            mortgage_balances[mortgage.id] = mortgage.balance

        # Mortgages created by housing events: id -> (rate, payment, start)
        event_mortgage_terms: Dict[str, tuple] = {}
        mortgage_property_map = {
            m.id: m.property_id for m in self.scenario.mortgages
        }

        # Initialize cost basis — for simplicity, assume initial basis
        # equals current balance (all contributions up to now).
        # A real implementation would track actual contributions.
        cost_basis = CostBasisTracker()
        for account_id, account in self.accounts.items():
            if account.tax_treatment == "taxable":
                cost_basis.set_basis(account_id, account.balance)
                # Aggregate-basis policy: initial basis equals balance.

        rates = self.scenario.economic.get_rate(scenario_name)
        inflation_rate = rates["general_inflation"]
        withdrawal_engine = WithdrawalEngine(self.accounts, cost_basis)
        tax_law_registry = TaxLawRegistry()

        # Monetary policy for convention-aware conversion
        monetary_policy = MonetaryPolicy(
            convention=self.scenario.monetary_convention,
            base_year=self.start_year,
            inflation=inflation_rate,
        )

        # Track MAGI by year for IRMAA 2-year lookback
        magi_history: Dict[int, float] = {}

        # Withdrawal strategy tracking
        portfolio_peak = 0.0

        # Starting portfolio for guardrails planned path
        self._starting_portfolio = sum(
            b for b in balances.values() if b > 0
        )

        # Historical return sequence index (for sequential replay)
        _hist_idx = 0

        # Run until the LAST death: the younger/longer-lived person sets
        # the horizon (estate tax is assessed when both are gone).
        max_year = max(
            self.scenario.primary.birth_date.year
            + self.scenario.primary.longevity_age,
            self.scenario.spouse.birth_date.year
            + self.scenario.spouse.longevity_age,
        ) + 1

        for year in range(self.start_year, max_year):
            context = make_year_context(
                year, self.start_year,
                self.scenario.primary.birth_date.year,
                self.scenario.spouse.birth_date.year,
            )
            primary_age = context.primary_age
            spouse_age = context.spouse_age
            younger_age = context.younger_age
            years_from_base = context.years_from_base
            yearly_state = make_state(context, balances, mortgage_balances)

            # --- Filing status ---
            filing_status = determine_annual_filing_status(
                year, primary_alive=True, spouse_alive=True,
                death_year_spouse=None,  # TODO: track spouse death year
                has_dependents=False,
            )

            # Get tax law for this year
            law = tax_law_registry.law_for_year(year)

            if (primary_age > self.scenario.primary.longevity_age
                    and spouse_age > self.scenario.spouse.longevity_age):
                break

            # --- Step 1: Investment returns (with optional volatility) ---
            for account_id in list(balances.keys()):
                balance = balances[account_id]
                if balance <= 0:
                    continue
                account = self.accounts[account_id]
                convention_adjusted = False

                if account.account_type == "real_estate":
                    base_rate = rates["housing_appreciation"]
                elif account.is_depreciating:
                    base_rate = -0.04
                elif account.growth_rate == 0:
                    base_rate = 0
                else:
                    # Use equity glidepath if configured.  Allocation
                    # rates are already converted to the active
                    # convention inside get_growth_rate_for_allocation.
                    convention_adjusted = True
                    allocation = self.get_equity_allocation(
                        self._account_owner_age(account, year)
                    )
                    # Account-level override
                    if account.equity_pct is not None:
                        bond_pct = 1.0 - account.equity_pct
                        allocation = AssetAllocation(
                            equity_pct=account.equity_pct,
                            bond_pct=bond_pct,
                        )
                    base_rate = self.get_growth_rate_for_allocation(
                        account, allocation
                    )

                # Determine the actual return rate for this year
                if (self._historical_return_override is not None
                        and _hist_idx < len(self._historical_return_override)
                        and account.account_type not in ("real_estate",)):
                    # Historical sequences are NOMINAL market returns:
                    # in REAL mode deflate them to constant dollars.
                    actual_rate = self._historical_return_override[_hist_idx]
                    if (self.scenario.monetary_convention
                            == MonetaryConvention.REAL):
                        actual_rate = ((1.0 + actual_rate)
                                       / (1.0 + inflation_rate) - 1.0)
                elif return_volatility > 0:
                    generator = rng if rng is not None else np.random.default_rng()
                    actual_rate = generator.normal(base_rate, return_volatility)
                else:
                    actual_rate = base_rate

                # Non-allocation rates (real estate, depreciating assets,
                # cash) come in the real convention — convert once here.
                # Allocation rates were already converted above.
                if not convention_adjusted and not (
                        self._historical_return_override is not None
                        and account.account_type not in ("real_estate",)):
                    actual_rate = monetary_policy.portfolio_return_to_convention(
                        actual_rate, inflation_rate,
                    )

                growth = balance * actual_rate
                balances[account_id] = balance + growth

            # Advance historical return index (one position per simulated year)
            if self._historical_return_override is not None:
                _hist_idx += 1

            # --- Step 2: Retirement status (used below) ---
            primary_retired = self._is_retired(year, self.scenario.primary)
            spouse_retired = self._is_retired(year, self.scenario.spouse)

            # --- Step 3: Income ---
            income_data = self.calculate_annual_income(year, scenario_name)
            annual_income = income_data["total"]

            # In NOMINAL mode, inflate income to year-of dollars
            annual_income = monetary_policy.adjust_for_inflation(
                annual_income, year, inflation_rate,
            )

            # Social Security
            ss_income = 0.0
            if primary_age >= self.scenario.social_security.primary_claiming_age:
                ss_income += self.calculate_social_security(
                    year, self.scenario.primary)
            if spouse_age >= self.scenario.social_security.spouse_claiming_age:
                ss_income += self.calculate_social_security(
                    year, self.scenario.spouse)
            # In NOMINAL mode, inflate SS (it already has COLA but
            # we need the base-year → year inflation for convention)
            ss_income = monetary_policy.adjust_for_inflation(
                ss_income, year, inflation_rate,
            )
            annual_income += ss_income
            total_ss += ss_income

            # --- Step 4: Expenses ---
            expense_data = self.calculate_annual_expenses(
                year, scenario_name, mortgage_balances=mortgage_balances,
                event_mortgage_terms=event_mortgage_terms,)
            annual_expenses = expense_data["total"]

            # In NOMINAL mode, inflate expenses to year-of dollars
            annual_expenses = monetary_policy.adjust_for_inflation(
                annual_expenses, year, inflation_rate,
            )

            # Medical inflation: healthcare grows at medical minus
            # general inflation, compounded from the current cost level.
            excess = rates.get("medical_inflation", 0.034) - rates.get(
                "general_inflation", 0.025)
            annual_expenses += monetary_policy.adjust_for_inflation(
                self._medical_inflation_extra(year, excess),
                year, inflation_rate,
            )

            # --- Step 4b: IRMAA Medicare surcharges (per-person) ---
            # 2-year lookback: use MAGI from 2 years prior
            lookback_year = year - 2
            magi_2yr_ago = magi_history.get(lookback_year, 0.0)

            # Count people on Medicare (age >= 65 with Medicare coverage)
            num_medicare = 0
            if self.scenario.primary.coverage_at_age(primary_age) == "medicare":
                num_medicare += 1
            if self.scenario.spouse.coverage_at_age(spouse_age) == "medicare":
                num_medicare += 1

            irmaa_amount = 0.0
            if num_medicare > 0:
                # IRS uses combined household MAGI for IRMAA tiers
                irmaa_amount = tax_law_irmaa(magi_2yr_ago, law, num_people=num_medicare)
                annual_expenses += irmaa_amount

            # --- Step 4c: ACA subsidy (per-person, pre-Medicare) ---
            # The subsidy depends on MAGI, which includes withdrawal
            # income, so it is recomputed inside the fixed-point loop
            # below rather than here.  Only eligibility is determined now.
            aca_family_size = 0
            if primary_age < 65 and self.scenario.primary.coverage_at_age(primary_age) == "aca":
                aca_family_size += 1
            if spouse_age < 65 and self.scenario.spouse.coverage_at_age(spouse_age) == "aca":
                aca_family_size += 1
            # Children under 26 ride on the parents' ACA plan
            aca_family_size += self._dependents_under_26(year)

            # --- Step 4d: Apply withdrawal strategy (if retired) ---
            total_portfolio_value = sum(b for b in balances.values() if b > 0)

            if primary_retired and spouse_retired:
                # Anchor the strategy on THIS year's planned expenses
                # (post-inflation, post medical-excess, post IRMAA), not
                # a year-1 snapshot: when expense streams end (mortgage
                # payoff, childcare, lease), spending must follow them.
                annual_expenses = self.apply_withdrawal_strategy(
                    year, annual_expenses, total_portfolio_value,
                    portfolio_peak, expense_data,
                )

            # --- Step 4e: Roth conversions ---
            rc_result = process_roth_conversions(
                self.scenario.roth_conversions, year, balances)
            if rc_result.total_converted > 0:
                # Track for later use when building ordinary income
                _roth_conversion_income = rc_result.ordinary_income_added
            else:
                _roth_conversion_income = 0.0

            # --- Step 4f: Pre-tax rollovers (e.g. 401k -> trad IRA) ---
            # Run AFTER conversions of the same year (rollover feeds next
            # year's ladder) and BEFORE withdrawals so the source account
            # balance is fully moved.
            for ro in self.scenario.rollover_events:
                if ro.event_date.year != year:
                    continue
                source = balances.get(ro.source_account, 0.0)
                if source <= 0:
                    continue
                balances[ro.source_account] = 0.0
                balances[ro.target_account] = (
                    balances.get(ro.target_account, 0.0) + source)
                # Pre-tax -> pre-tax: no basis change

            # --- Step 5: Withdrawals with tax gross-up (fixed point) ---
            # Withdrawals must fund expenses AND taxes.  Taxes depend on
            # the income the withdrawals create (ordinary income, capital
            # gains, taxable SS), so the required withdrawal is a fixed
            # point:  needed = expenses + taxes - income.
            #
            # The ACA subsidy also depends on withdrawal income (MAGI) and
            # taxable SS depends on provisional income, so both are
            # recomputed each pass.  Simple iteration converges because the
            # marginal tax rate on withdrawals is < 100% (monotone
            # contraction); typically 2-4 passes.
            #
            # Trials run against COPIES of balances/basis so the fixed point
            # is computed without mutating real state; the withdrawal
            # executes exactly once after convergence.
            trial_needed = 0.0
            trial_magi = annual_income  # withdrawal-inclusive MAGI
            converged = False
            taxes = 0.0
            aca_subsidy = 0.0
            new_needed = 0.0
            tax_ordinary_nominal = 0.0
            tax_cg_nominal = 0.0
            for _ in range(20):
                trial_balances = dict(balances)
                basis_snapshot = dict(cost_basis.basis_by_account)
                # Always execute (even at needed=0) so the forced RMD
                # floor is part of the fixed point: RMDs are mandatory
                # regardless of spending need, and their tax consequences
                # must feed back into the required withdrawal.
                trial_wd = withdrawal_engine.execute_withdrawals(
                    trial_needed, trial_balances, year, primary_age,
                    spouse_age, sale_date=date(year, 12, 31),
                )
                # Undo trial basis mutation
                cost_basis.basis_by_account.clear()
                cost_basis.basis_by_account.update(basis_snapshot)

                # ACA subsidy on trial withdrawal-inclusive MAGI.  The
                # subsidy can only offset the healthcare premium (the
                # ACA-eligible medical spend), not every expense — a
                # household's out-of-pocket is never reduced below
                # expenses minus the premium it actually replaces.
                if aca_family_size > 0:
                    aca_subsidy = tax_law_aca(
                        trial_magi, aca_family_size, law, self.scenario.state)
                premium_base = monetary_policy.adjust_for_inflation(
                    self._medical_expenses_base(year), year, inflation_rate)
                subsidy_used = min(aca_subsidy, premium_base)
                expenses_after_subsidy = max(
                    0.0, annual_expenses - subsidy_used)

                # --- Build TaxableIncome from trial withdrawals ---
                # SS taxable portion (income BEFORE SS was added, but
                # INCLUDING withdrawal income — provisional income in
                # retirement is driven by withdrawals).
                withdrawal_ordinary = sum(
                    w.taxable_amount for w in trial_wd
                    if w.tax_treatment == "ordinary")
                withdrawal_cg = sum(
                    w.capital_gain for w in trial_wd
                    if w.tax_treatment == "capital_gains")
                tax_free = sum(
                    w.amount for w in trial_wd
                    if w.tax_treatment == "tax_free")

                non_ss_income = income_data["total"]  # wages + other non-SS income
                # Provisional income for SS taxation includes capital
                # gains; ordinary income does not.  Non-SS base-year
                # income inflates in NOMINAL mode (withdrawal/conversion
                # flows are already year-of dollars).
                if (self.scenario.monetary_convention
                        == MonetaryConvention.NOMINAL):
                    inflate = ((1.0 + inflation_rate)
                               ** (year - self.start_year))
                    other_income = ((non_ss_income + _roth_conversion_income)
                                    * inflate + withdrawal_ordinary
                                    + withdrawal_cg)
                else:
                    other_income = (non_ss_income + _roth_conversion_income
                                    + withdrawal_ordinary + withdrawal_cg)
                taxable_ss = self.calculate_ss_taxable(ss_income, other_income)

                # Ordinary income = non-SS wages/withdrawals/conversions +
                # taxable SS portion (capital gains stay separate).
                # calculate_annual_income returns base-year dollars: in
                # NOMINAL mode inflate the base-year components to
                # year-of dollars (withdrawal/conversion flows are
                # already year-of).
                if (self.scenario.monetary_convention
                        == MonetaryConvention.NOMINAL):
                    inflate = ((1.0 + inflation_rate)
                               ** (year - self.start_year))
                    ordinary = ((non_ss_income + _roth_conversion_income)
                                * inflate + withdrawal_ordinary + taxable_ss)
                    capital_gains = withdrawal_cg
                else:
                    ordinary = (non_ss_income + _roth_conversion_income
                                + withdrawal_ordinary + taxable_ss)
                    capital_gains = withdrawal_cg

                # Convert to nominal for tax calculation (tax brackets are
                # always nominal; REAL-mode values convert, then back).
                tax_ordinary_nominal = monetary_policy.to_nominal_for_tax(
                    ordinary, year, inflation_rate,
                )
                tax_cg_nominal = monetary_policy.to_nominal_for_tax(
                    capital_gains, year, inflation_rate,
                )
                tax_free_nominal = monetary_policy.to_nominal_for_tax(
                    tax_free, year, inflation_rate,
                )
                taxable_income_for_tax = TaxableIncome(
                    ordinary=tax_ordinary_nominal,
                    capital_gains=tax_cg_nominal,
                    tax_free=tax_free_nominal,
                    total=(tax_ordinary_nominal + tax_cg_nominal
                           + tax_free_nominal),
                )
                # Child Tax Credit: dependents under 17
                num_children = sum(
                    1 for dep in self.scenario.dependents
                    if 0 <= year - dep.birth_date.year < 17)
                taxes_nominal = self.calculate_taxes(
                    year, taxable_income_for_tax, scenario_name,
                    inflation_rate=inflation_rate,
                    years_from_base=years_from_base,
                    num_children=num_children)
                # Convert tax back to the active convention (NIIT is already
                # included in calculate_taxes() via tax_law)
                taxes = monetary_policy.from_nominal_after_tax(
                    taxes_nominal, year, inflation_rate,
                )

                # Withdrawal-inclusive MAGI for the next ACA pass
                trial_magi = (annual_income + withdrawal_ordinary
                              + withdrawal_cg)

                new_needed = max(0.0, expenses_after_subsidy + taxes
                                 - annual_income)
                if abs(new_needed - trial_needed) <= max(
                        0.05, abs(trial_needed) * 1e-6):
                    converged = True
                    break
                trial_needed = new_needed

            if not converged:
                # Safety net (marginal rates < 100% make this rare):
                # damped average of the last two iterates.
                trial_needed = (trial_needed + new_needed) / 2.0

            # Execute exactly once on real balances at the converged amount
            needed = trial_needed
            if needed > 0:
                withdrawals = withdrawal_engine.execute_withdrawals(
                    needed, balances, year, primary_age, spouse_age,
                    sale_date=date(year, 12, 31),
                )
            else:
                withdrawals = []

            # If withdrawals could not fully cover the required amount
            # (illiquid assets remain, e.g. real estate), the household is
            # out of savings even though net worth may still be positive.
            covered = sum(w.amount for w in withdrawals)
            if (covered < needed - 1.0
                    and out_of_savings_year is None):
                out_of_savings_year = year

            total_taxes += taxes
            total_aca_subsidy += aca_subsidy

            # Record this year's MAGI for future IRMAA lookback
            # (MAGI is always nominal for IRS purposes)
            magi = tax_ordinary_nominal + tax_cg_nominal
            magi_history[year] = magi

            # --- Step 7c: Allocate surplus savings into accounts ---
            # Savings = income - expenses - taxes.  Distribute by account
            # contribution priority (401k → HSA → Roth → brokerage …).
            # Only while at least one person is still working.
            if not primary_retired or not spouse_retired:
                available_savings = annual_income - annual_expenses - taxes
                if available_savings > 0:
                    contribs = withdrawal_engine.contribute(
                        balances, available_savings)
                    total_contributions += sum(contribs.values())

            # --- Step 8: Windfalls ---
            for windfall in self.scenario.windfalls:
                if windfall.date.year == year:
                    target = windfall.goes_to_account
                    if not target or target not in balances:
                        continue
                    # Transfers debit the source account (e.g. 529
                    # superfund moves brokerage cash into the 529)
                    if windfall.source_account:
                        source_balance = balances.get(
                            windfall.source_account, 0.0)
                        if source_balance <= 0:
                            continue
                        amount = min(windfall.amount, source_balance)
                        balances[windfall.source_account] -= amount
                    else:
                        amount = windfall.amount
                    balances[target] += amount
                    # Increase basis for taxable windfalls
                    acct = self.accounts.get(target)
                    if acct and acct.tax_treatment == "taxable":
                        current_basis = cost_basis.get_basis(target, 0.0)
                        cost_basis.set_basis(target, current_basis + amount)

            # --- Step 8b: Housing events ---
            for he in self.scenario.housing_events:
                he_result = process_housing_event(
                    he, year, balances, mortgage_balances,
                    cost_basis=cost_basis.get_basis(
                        he.property_id, 0.0) if he.property_id
                        else cost_basis.get_basis("real_estate", 0.0),
                    filing_status=filing_status,
                    mortgage_property_map=mortgage_property_map,
                    event_mortgage_terms=event_mortgage_terms,
                )
                if he_result.event_type != "none":
                    taxes += he_result.tax_due
                    # New property basis = purchase price (aggregate policy)
                    if he.property_id and he.purchase_price > 0:
                        cost_basis.set_basis(
                            he.property_id, he.purchase_price)

            # --- Step 9: Track net worth ---
            total_assets = sum(b for b in balances.values() if b > 0)
            total_liabs = sum(abs(b) for b in balances.values() if b < 0)
            total_liabs += sum(
                b for b in mortgage_balances.values() if b > 0)
            net_worth = total_assets - total_liabs

            # Shared projection-state boundary. The legacy result contract
            # remains unchanged while yearly data becomes inspectable.
            yearly_state.income = income_data
            yearly_state.expenses = expense_data
            yearly_state.withdrawals = withdrawals
            yearly_state.taxes = taxes
            yearly_state.healthcare = {
                "aca_subsidy": aca_subsidy,
                "irmaa": irmaa_amount,
            }
            yearly_state.events.append({"type": "year_complete"})

            if projections is not None:
                projections.append({
                    "year": year,
                    "income": annual_income,
                    "expenses": annual_expenses,
                    "taxes": taxes,
                    "aca_subsidy": aca_subsidy,
                    "net_worth": net_worth,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabs,
                })

            if net_worth > peak_nw:
                peak_nw = net_worth

            # Update portfolio peak for guardrails/withdrawal strategies
            total_portfolio = sum(b for b in balances.values() if b > 0)
            if total_portfolio > portfolio_peak:
                portfolio_peak = total_portfolio

            if net_worth <= 0 and out_of_savings_year is None:
                out_of_savings_year = year

            # --- Step 10: Estate tax (at end of life) ---
            younger_longevity = (self.scenario.primary.longevity_age
                if self.scenario.primary.birth_date > self.scenario.spouse.birth_date
                else self.scenario.spouse.longevity_age)
            if (younger_age >= younger_longevity
                    and total_estate_tax == 0.0):
                # The exemption is inflation-indexed (nominal), so the
                # estate must be converted to nominal before comparing.
                estate_nominal = monetary_policy.to_nominal_for_tax(
                    net_worth, year, inflation_rate)
                estate_tax_nominal = tax_law_estate(
                    estate_nominal, law, FilingStatus.MFJ)
                total_estate_tax = monetary_policy.from_nominal_after_tax(
                    estate_tax_nominal, year, inflation_rate)

        final_nw = (sum(balances.values())
                    - sum(b for b in mortgage_balances.values() if b > 0))
        # Net of estate tax for success calculation
        final_nw_after_estate = final_nw - total_estate_tax
        success = (final_nw_after_estate > self.scenario.legacy_goal
                   and out_of_savings_year is None)

        return {
            "success": success,
            "final_net_worth": final_nw,
            "final_net_worth_after_estate_tax": final_nw_after_estate,
            "estate_tax": total_estate_tax,
            "aca_subsidy": total_aca_subsidy,
            "peak_net_worth": peak_nw,
            "lifetime_taxes": total_taxes,
            "lifetime_ss": total_ss,
            "lifetime_contributions": total_contributions,
            "out_of_savings_year": out_of_savings_year,
            **({"projections": projections} if projections is not None else {}),
        }

    # ------------------------------------------------------------------
    # Asset location suggestions
    # ------------------------------------------------------------------
    def suggest_asset_location(self, accounts: Optional[List[Account]] = None) -> Dict[str, str]:
        """Suggest which asset class should be held in each account for tax efficiency.

        This is a recommendation only — it does not move money or change
        account settings.  The mapping follows standard asset-location wisdom:

        * **Roth IRA / Roth 401(k)** → "equity" (highest growth, tax-free)
        * **Traditional IRA / 401(k)** → "bond" (ordinary income, avoid
          wasting tax-free growth space)
        * **Taxable brokerage** → "equity" (tax-efficient index funds / munis;
          here we still suggest equity since index funds are more tax-efficient
          than bonds in taxable)
        * **HSA** → "equity" (triple tax advantage)
        * **Everything else** → "mixed" (no strong recommendation)

        Args:
            accounts: List of Account objects to evaluate.  If None, uses
                all accounts in the current scenario.

        Returns:
            Dict mapping account_id to suggested asset_class string.
        """
        if accounts is None:
            accounts = list(self.accounts.values())

        suggestions: Dict[str, str] = {}
        for account in accounts:
            acct_type = account.account_type.lower()
            tax = account.tax_treatment.lower()

            # Roth accounts → equity (tax-free growth)
            if tax == "roth" or "roth" in acct_type:
                suggestions[account.id] = "equity"
            # HSA → equity (triple tax advantage)
            elif acct_type == "hsa":
                suggestions[account.id] = "equity"
            # Traditional / pre-tax retirement accounts → bonds
            # (withdrawing bonds from pre-tax accounts avoids wasting
            #  tax-free growth space on low-return assets)
            elif tax == "pre_tax" or acct_type in ("401k", "trad_ira", "trad_401k", "traditional_ira"):
                suggestions[account.id] = "bond"
            # Taxable brokerage → equity (tax-efficient index funds)
            elif tax == "taxable":
                suggestions[account.id] = "equity"
            # Everything else (checking, real estate, vehicles, etc.)
            else:
                suggestions[account.id] = "mixed"

        return suggestions

    # ------------------------------------------------------------------
    # Deterministic cash flow projection
    # ------------------------------------------------------------------
    def project_cash_flow(self, scenario_name: str = "mean") -> List[Dict]:
        """Generate year-by-year cash flow projection (deterministic)."""
        from .approximations import (
            ApproximationTracker, AGGREGATE_BASIS_WARNING,
            DETERMINISTIC_TAXES_WARNING, DETERMINISTIC_RETURNS_WARNING,
        )

        projections = []
        cost_basis = CostBasisTracker()
        has_taxable = False
        for account_id, account in self.accounts.items():
            if account.tax_treatment == "taxable":
                cost_basis.set_basis(account_id, account.balance)
                has_taxable = True

        # Track approximations for this projection run
        tracker = ApproximationTracker()
        tracker.add(DETERMINISTIC_RETURNS_WARNING)
        tracker.add(DETERMINISTIC_TAXES_WARNING)
        if has_taxable:
            tracker.add(AGGREGATE_BASIS_WARNING)

        rates = self.scenario.economic.get_rate(scenario_name)
        inflation_rate = rates["general_inflation"]
        monetary_policy = MonetaryPolicy(
            convention=self.scenario.monetary_convention,
            base_year=self.start_year,
            inflation=inflation_rate,
        )
        total_estate_tax = 0.0

        # Track mortgage balances so deterministic net worth matches the
        # Monte Carlo convention (liabilities reduce net worth, payments
        # amortize the balance).
        mortgage_balances: Dict[str, float] = {}
        for mortgage in self.scenario.mortgages:
            mortgage_balances[mortgage.id] = mortgage.balance

        # Running account balances (mirrors the MC loop so housing events
        # mutate the same state: property sold/added, mortgages paid off
        # or created, event mortgages amortized).
        balances: Dict[str, float] = {}
        for account_id, account in self.accounts.items():
            balances[account_id] = account.balance
        income_history: Dict[int, float] = {}  # IRMAA 2-year lookback
        event_mortgage_terms: Dict[str, tuple] = {}
        mortgage_property_map = {
            m.id: m.property_id for m in self.scenario.mortgages
        }

        # Run until the LAST death: the younger/longer-lived person sets
        # the horizon (estate tax is assessed when both are gone).
        max_year = max(
            self.scenario.primary.birth_date.year
            + self.scenario.primary.longevity_age,
            self.scenario.spouse.birth_date.year
            + self.scenario.spouse.longevity_age,
        ) + 1

        for year in range(self.start_year, max_year):
            context = make_year_context(
                year, self.start_year,
                self.scenario.primary.birth_date.year,
                self.scenario.spouse.birth_date.year,
            )
            primary_age = context.primary_age
            spouse_age = context.spouse_age
            younger_age = context.younger_age
            years_from_base = context.years_from_base
            yearly_state = make_state(context)

            if (primary_age > self.scenario.primary.longevity_age
                    and spouse_age > self.scenario.spouse.longevity_age):
                break

            # Grow balances at deterministic (volatility-free) rates
            for account_id in list(balances.keys()):
                account = self.accounts.get(account_id)
                if account is None or balances[account_id] <= 0:
                    continue
                rate = self._account_growth_rate(account, year, rates)
                balances[account_id] *= (1 + rate)

            income = self.calculate_annual_income(year, scenario_name)

            # Social Security (mirrors the Monte Carlo path: per-person
            # claiming age with COLA).
            ss_income = 0.0
            ss = self.scenario.social_security
            if ss:
                if primary_age >= ss.primary_claiming_age:
                    ss_income += self.calculate_social_security(
                        year, self.scenario.primary)
                if spouse_age >= ss.spouse_claiming_age:
                    ss_income += self.calculate_social_security(
                        year, self.scenario.spouse)
            # In NOMINAL mode, inflate income and SS to year-of dollars
            # (MC parity; REAL mode is identity).
            income["total"] = monetary_policy.adjust_for_inflation(
                income["total"], year, inflation_rate)
            ss_income = monetary_policy.adjust_for_inflation(
                ss_income, year, inflation_rate)
            if ss_income > 0:
                income["total"] += ss_income
                income["by_source"]["Social Security"] = ss_income

            income_history[year] = income["total"]

            expenses = self.calculate_annual_expenses(
                year, scenario_name, mortgage_balances=mortgage_balances,
                event_mortgage_terms=event_mortgage_terms)

            # In NOMINAL mode, inflate expenses to year-of dollars
            # (MC parity; REAL mode is identity).
            expenses["total"] = monetary_policy.adjust_for_inflation(
                expenses["total"], year, inflation_rate)

            # Medical inflation excess — parity with the Monte Carlo path.
            expenses["total"] += monetary_policy.adjust_for_inflation(
                self._medical_inflation_extra(
                    year, rates["medical_inflation"] - inflation_rate),
                year, inflation_rate)

            # ACA subsidy (pre-Medicare, per-person)
            aca_family_size = 0
            if primary_age < 65 and self.scenario.primary.coverage_at_age(primary_age) == "aca":
                aca_family_size += 1
            if spouse_age < 65 and self.scenario.spouse.coverage_at_age(spouse_age) == "aca":
                aca_family_size += 1
            # Children under 26 ride on the parents' ACA plan
            aca_family_size += self._dependents_under_26(year)

            # IRMAA Medicare surcharges (2-year lookback on MAGI — the
            # deterministic path uses income-only MAGI; MC includes
            # withdrawals).  Mirrors the Monte Carlo step 4b.
            num_medicare = 0
            if self.scenario.primary.coverage_at_age(primary_age) == "medicare":
                num_medicare += 1
            if self.scenario.spouse.coverage_at_age(spouse_age) == "medicare":
                num_medicare += 1
            if num_medicare > 0:
                irmaa_amount = tax_law_irmaa(
                    income_history.get(year - 2, 0.0),
                    TaxLawRegistry().law_for_year(year),
                    num_people=num_medicare,
                )
                expenses["total"] += monetary_policy.adjust_for_inflation(
                    irmaa_amount, year, inflation_rate)

            aca_subsidy = 0.0
            if aca_family_size > 0:
                # Use the versioned law pack so deterministic and MC
                # subsidy amounts agree.
                from .tax_law import TaxLawRegistry, calculate_aca_subsidy as tax_law_aca_calc
                law = TaxLawRegistry().law_for_year(year)
                aca_subsidy = tax_law_aca_calc(
                    income["total"], aca_family_size, law, self.scenario.state)

            # Build TaxableIncome (simplified — all income as ordinary
            # for deterministic projection; real sim handles this
            # properly).  Social Security is partially taxable: only the
            # provisional-income share counts as ordinary (MC parity).
            ss_in_total = income.get("by_source", {}).get(
                "Social Security", 0.0)
            non_ss = income["total"] - ss_in_total
            taxable_ss = self.calculate_ss_taxable(ss_in_total, non_ss)
            ordinary_for_tax = non_ss + taxable_ss
            # Tax brackets are nominal: in REAL mode convert income to
            # nominal; in NOMINAL mode income is already year-of dollars
            # (inflated above).
            if (self.scenario.monetary_convention
                    == MonetaryConvention.NOMINAL):
                income_for_tax = ordinary_for_tax
            else:
                income_for_tax = monetary_policy.to_nominal_for_tax(
                    ordinary_for_tax, year, inflation_rate)
            ti = TaxableIncome(
                ordinary=income_for_tax,
                capital_gains=0.0,
                tax_free=0.0,
                total=income_for_tax,
            )
            # Child Tax Credit: dependents under 17
            num_children = sum(
                1 for dep in self.scenario.dependents
                if 0 <= year - dep.birth_date.year < 17)
            taxes = self.calculate_taxes(
                year, ti, scenario_name,
                inflation_rate=inflation_rate,
                years_from_base=years_from_base,
                num_children=num_children)
            # Taxes are computed on nominal income: convert back to the
            # active convention (REAL mode deflates — MC parity).
            taxes = monetary_policy.from_nominal_after_tax(
                taxes, year, inflation_rate)

            # Housing events (sale/purchase/trade-up) — same in-place
            # semantics as the Monte Carlo path.
            for he in self.scenario.housing_events:
                he_result = process_housing_event(
                    he, year, balances, mortgage_balances,
                    cost_basis=cost_basis.get_basis(
                        he.property_id, 0.0) if he.property_id
                        else cost_basis.get_basis("real_estate", 0.0),
                    filing_status="MFJ",
                    mortgage_property_map=mortgage_property_map,
                    event_mortgage_terms=event_mortgage_terms,
                )
                if he_result.event_type != "none":
                    taxes += he_result.tax_due
                    if he.property_id and he.purchase_price > 0:
                        cost_basis.set_basis(
                            he.property_id, he.purchase_price)

            # Net worth from the running balances (assets + liabilities)
            total_assets = sum(
                b for b in balances.values() if b > 0)
            total_liabs = sum(
                abs(b) for b in balances.values() if b < 0)
            total_liabs += sum(
                b for b in mortgage_balances.values() if b > 0)
            net_worth = {
                "total_assets": total_assets,
                "total_liabilities": total_liabs,
                "net_worth": total_assets - total_liabs,
            }
            yearly_state.income = income
            yearly_state.expenses = expenses
            yearly_state.taxes = taxes
            yearly_state.healthcare = {"aca_subsidy": aca_subsidy}
            yearly_state.approximations = list(tracker.for_year(year))
            yearly_state.events.append({"type": "year_complete"})

            # Estate tax (at end of life, applied once)
            younger_longevity = (self.scenario.primary.longevity_age
                if self.scenario.primary.birth_date > self.scenario.spouse.birth_date
                else self.scenario.spouse.longevity_age)
            if (younger_age >= younger_longevity
                    and total_estate_tax == 0.0):
                total_estate_tax = self.calculate_estate_tax(
                    net_worth["net_worth"], "MFJ",
                    inflation_rate, years_from_base)

            projections.append({
                "year": year,
                "primary_age": primary_age,
                "spouse_age": spouse_age,
                "income": income["total"],
                "income_by_source": income["by_source"],
                "expenses": expenses["total"],
                "aca_subsidy": aca_subsidy,
                "expenses_by_category": expenses["by_category"],
                "taxes": taxes,
                "estate_tax": total_estate_tax if younger_age >= younger_longevity else 0.0,
                "net_cash_flow": income["total"] - expenses["total"] - taxes - aca_subsidy,
                "net_worth": net_worth["net_worth"],
                "total_assets": net_worth["total_assets"],
                "total_liabilities": net_worth["total_liabilities"],
                "approximations": [
                    a.as_dict() for a in tracker.for_year(year)
                ],
            })

        return projections
