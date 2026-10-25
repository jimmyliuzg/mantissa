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
from dataclasses import dataclass, field, replace
from enum import Enum

from .models import (
    Scenario, Person, Account, IncomeStream, Expense, ACCOUNT_TAX_DEFAULTS,
    Mortgage, Windfall, HousingEvent, RothConversion, RolloverEvent,
    Dependent, EconomicAssumptions, SocialSecurity, AgeEvent, TaxableIncome,
    AssetAllocation, GlidepathConfig, MonetaryConvention,
)

from .access import AccessLedger, reaches_age
from .monetary import MonetaryPolicy
from .fixes import process_housing_event, process_roth_conversions, apply_medical_inflation
from .tax_lots import calculate_121_exclusion
from .projection.services import make_year_context, make_state
from .sim_integration import calculate_401k_limit, compute_survivor_ss_benefit
from .household import (
    survivor_snapshot,
    normalize_filing_status,
    MortalityModel,
    rollover_pretax_ownership,
    stochastic_alive_snapshot,
)
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
    Values use the active convention. REAL-mode values are rebased annually
    so their nominal amount stays fixed; contributions establish new basis.
    Missing opening basis retains the market-value fallback with a warning.
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
                 cost_basis: CostBasisTracker, access_policy="unrestricted",
                 birth_dates=None, start_year=None):
        self.accounts = accounts
        self.cost_basis = cost_basis
        self.access_policy = access_policy
        self.access_start_year = start_year or datetime.now().year
        self.birth_dates = birth_dates or {}
        self.access = AccessLedger(accounts, start_year or datetime.now().year)
        self.nominal_factor = 1.0
        self.owner_map = {}
        self.owner_ages = {}
        self.sale_date = None
        self._withdrawals: List[WithdrawalResult] = []
        self.rmd_reference_balances = None
        self.rmd_year = None

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
        owner_map: Optional[Dict[str, str]] = None,
        access_date: Optional[date] = None,
    ) -> List[WithdrawalResult]:
        """Withdraw from accounts in tax-efficient order until *needed* is met.

        Returns a list of ``WithdrawalResult`` objects.  Side-effects
        update *balances* and ``cost_basis`` in place.
        """
        self.clear()
        self.rmd_year = year
        remaining = needed
        self.owner_map = owner_map or {}
        self.owner_ages = {"primary": primary_age, "spouse": spouse_age}
        self.sale_date = access_date or sale_date or date(year, 1, 1)
        # --- Step 1: Force RMDs from pre-tax accounts (age 73+) ---
        remaining = self._withdraw_rmds(
            balances, primary_age, spouse_age, remaining, owner_map)

        # --- Step 2: Taxable brokerage ---
        remaining = self._withdraw_from_category(
            balances, remaining,
            category_filter=lambda a: a.tax_treatment == "taxable" and a.account_type != "hsa",
            tax_treatment="capital_gains",
            sale_date=sale_date,
        )

        # --- Step 3: Pre-tax (401k, traditional IRA) ---
        remaining = self._withdraw_from_category(
            balances, remaining,
            category_filter=lambda a: a.tax_treatment == "pre_tax",
            tax_treatment="ordinary",
        )

        remaining = self._withdraw_from_category(
            balances, remaining, category_filter=lambda a: a.account_type == "hsa",
            tax_treatment="ordinary")

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
        owner_map: Optional[Dict[str, str]] = None,
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
            owner = (owner_map.get(account_id)
                     if owner_map is not None
                     else None) or (account.owner or "primary").lower()
            owner_age = spouse_age if owner == "spouse" else primary_age
            birth_year = self.rmd_year - owner_age if self.rmd_year is not None else 1955
            rmd_age = 75 if birth_year >= 1960 else 73 if birth_year >= 1951 else 72 if birth_year >= 1949 else 70.5
            if owner_age < rmd_age:
                continue
            group = "ira" if account.account_type in {"trad_ira", "traditional_ira"} else account_id
            reference = self.rmd_reference_balances.get(account_id, balance) if self.rmd_reference_balances is not None else balance
            groups.setdefault((owner, group), []).append((account_id, reference))

        rmds: Dict[str, float] = {}
        for (owner, _group), members in groups.items():
            age = spouse_age if owner == "spouse" else primary_age
            total_balance = sum(balance for _, balance in members)
            total_rmd = total_balance / _rmd_divisor(age)
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
                self.cost_basis.set_basis(destination, self.cost_basis.get_basis(destination, 0.0) + surplus)
                self._withdrawals.append(WithdrawalResult(
                    account_id=destination,
                    account_type=self.accounts[destination].account_type,
                    amount=surplus,
                    tax_treatment="rmd_reinvested",
                    taxable_amount=0.0,
                    capital_gain=0.0,
                ))

        return remaining

    def _owner(self, account):
        return self.owner_map.get(account.id, (account.owner or "primary").lower())

    def _old_enough(self, account, age):
        owner = self._owner(account)
        birth = self.birth_dates.get(owner)
        return (reaches_age(birth, age, self.sale_date) if birth
                else self.owner_ages.get(owner, 0) >= age)

    def available(self, account, balance):
        if not account.liquid or account.account_type in {"real_estate", "vehicle", "529"}:
            return 0.0
        if account.account_type == "hsa":
            return balance if self.access_policy == "penalty_free" and self._old_enough(account, 65) else 0.0
        if self.access_policy == "unrestricted" or account.tax_treatment == "taxable":
            return balance
        if account.tax_treatment == "pre_tax":
            return balance if self._old_enough(account, 59.5) else 0.0
        if account.tax_treatment == "roth":
            owner = self._owner(account)
            old = self._old_enough(account, 59.5)
            if account.account_type != "roth_ira":
                first = account.roth_first_contribution_year or self.access_start_year
                return balance if old and self.rmd_year >= first + 5 else 0.0
            if self.access.qualified(owner, self.rmd_year, old):
                return balance
            if account.account_type == "roth_ira":
                return min(balance, self.access.available_principal(owner, self.rmd_year, old) / self.nominal_factor)
        return 0.0

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
                    or account.account_type in {"vehicle", "529"}
                    or not account.liquid):
                continue
            balance = balances.get(account_id, 0.0)
            if balance <= 0:
                continue

            withdraw = min(remaining, self.available(account, balance))
            if withdraw <= 0:
                continue

            # For taxable accounts, compute capital gain portion
            capital_gain = 0.0
            taxable_amount = 0.0
            if tax_treatment == "capital_gains":
                basis_used = self.cost_basis.debit_basis(account_id, self.cost_basis.get_basis(account_id) * withdraw / balance)
                capital_gain = (0.0 if account.account_type in {"checking", "cash", "savings", "money_market"}
                                else withdraw - basis_used)
                taxable_amount = capital_gain
            elif tax_treatment == "ordinary":
                taxable_amount = withdraw
            # tax_free: taxable_amount stays 0

            if account.tax_treatment == "roth" and account.account_type == "roth_ira":
                self.access.consume(self._owner(account), withdraw * self.nominal_factor)
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
        year: Optional[int] = None,
        active_owners: Optional[set] = None,
        ages: Optional[dict] = None,
        wages_by_owner: Optional[dict] = None,
        monetary_factor: float = 1.0,
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
        owner_deferrals = {}
        for account in eligible:
            if remaining <= 0:
                break

            if year is not None and account.contribution_end_date and date(year, 1, 1) >= account.contribution_end_date:
                continue
            workplace = account.account_type in {"401k", "trad_401k", "roth_401k"}
            if workplace and active_owners is not None and account.owner not in active_owners:
                continue
            cap = account.contribution_caps_by_year.get(year, account.annual_contribution_cap)
            # An explicit scheduled zero means no contribution, unlike legacy cap=0 (unlimited).
            if year in account.contribution_caps_by_year and cap == 0:
                continue
            employee = min(remaining, cap / monetary_factor) if cap > 0 else remaining
            if workplace and year is not None:
                legal = calculate_401k_limit((ages or {}).get(account.owner, 0), year)
                owner_limit = legal / monetary_factor
                if wages_by_owner is not None:
                    owner_limit = min(owner_limit, wages_by_owner.get(account.owner, 0.0))
                employee = min(employee, max(0.0, owner_limit - owner_deferrals.get(account.owner, 0.0)))
                owner_deferrals[account.owner] = owner_deferrals.get(account.owner, 0.0) + employee
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
            if account.tax_treatment == "roth" and account.account_type == "roth_ira":
                self.access.add_contribution((account.owner or "primary").lower(), employee * self.nominal_factor, year)
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
        total_cost = marginal_tax + irmaa_cost - aca_subsidy  # marginal_tax already includes NIIT

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
        if scenario.withdrawal_access_policy not in {"penalty_free", "unrestricted"}:
            raise ValueError("Unknown withdrawal_access_policy")
        self.accounts = {a.id: a for a in scenario.accounts}
        for a in scenario.accounts:
            expected = ACCOUNT_TAX_DEFAULTS.get(a.account_type)
            if expected and a.tax_treatment != expected and not (a.account_type == "401k" and a.tax_treatment == "roth"):
                raise ValueError(f"Account {a.id}: tax_treatment conflicts with retirement account type")
        if scenario.surplus_account_id is not None:
            destination = self.accounts.get(scenario.surplus_account_id)
            if not destination or not destination.liquid or destination.tax_treatment != "taxable" or destination.account_type in {"real_estate", "vehicle", "hsa", "529"}:
                raise ValueError("surplus_account_id must reference a liquid unrestricted taxable account")
        self.start_year = scenario.start_year or datetime.now().year
        if scenario.balance_date and scenario.balance_date != date(self.start_year, 1, 1):
            warnings.warn(
                "Balances are dated inside a year but this engine projects whole years. "
                "Use consistent January opening balances or a later start_year; "
                "do not treat full-year cash flow as a remaining-year forecast.", UserWarning)
        # When set by MonteCarloEngine for historical simulations, the planner
        # uses this list of sequential returns instead of random gaussian draws.
        self._historical_return_override: Optional[List[float]] = None
        self.model_warnings = []
        if scenario.balance_date and scenario.balance_date != date(self.start_year, 1, 1):
            self.model_warnings.append("Whole-year model: starting balance dates differ from January opening balances; completed flows are not netted out.")
        missing_basis = [a.id for a in scenario.accounts if a.tax_treatment == "taxable" and a.balance > 0 and a.cost_basis is None and a.account_type not in {"checking", "cash", "savings", "money_market", "vehicle"}]
        if missing_basis:
            self.model_warnings.append("Missing aggregate cost_basis; market value assumed for: " + ", ".join(missing_basis))
        if any(w.source_account and w.is_taxable and w.taxable_amount is None for w in scenario.windfalls):
            self.model_warnings.append("Sourced windfalls without taxable_amount are treated as transfers with zero modeled income; reconcile K-1 income and basis separately.")
        if str(scenario.state).upper() != "CA":
            self.model_warnings.append("State income tax is modeled only for California. This plan omits state income tax for the selected state; results are incomplete for that component.")
        self.model_warnings.append("Access policy support is conservative: annual opening-date eligibility, declared Roth IRA contribution/conversion principal with five-year clocks, and explicit qualified HSA funding. SEPP, separation exceptions, inherited-account rules, penalties, IRA nondeductible basis and full tax-return/K-1 rules are not modeled. Investment distributions use declared yields or simplified profiles.")
        if scenario.withdrawal_access_policy == "unrestricted":
            self.model_warnings.append("Unrestricted withdrawal policy bypasses retirement access restrictions; bridge feasibility is not validated.")
        if any(a.tax_treatment == "roth" and a.roth_first_contribution_year is None for a in scenario.accounts):
            self.model_warnings.append("Missing Roth first-contribution year: opening year is used as a conservative five-year clock; undeclared contribution basis is zero.")
        # Stress level (0..1): discretionary expenses are cut by
        # min_reduction × stress_level (behavioral response to market
        # stress).  CLI --stress and the `stress` command set it.
        self.input_readiness = {"provisional": False, "access_assessed": True, "items": []}
        self.stress_level = 0.0
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
        
        from .config.readiness import resolve_inputs
        config, readiness = resolve_inputs(config)
        validate_config(config).raise_for_errors()

        # Parse config into Scenario
        # This is a simplified parser - full implementation would handle all fields
        from datetime import date
        
        primary_cfg = config["primary"]
        spouse_cfg = config.get("spouse")
        for who, pcfg in (("primary", primary_cfg), ("spouse", spouse_cfg or {})):
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

        # Issue #3: spouse is optional. A null or missing spouse means
        # a single-household plan. The projection horizon will be
        # derived from the primary alone (see _projection_max_year).
        spouse = None
        if spouse_cfg:
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
                         ):
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
                tax_treatment=acc_config.get("tax_treatment", ACCOUNT_TAX_DEFAULTS.get(acc_config["type"], "taxable")),
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
                asset_class=acc_config.get("asset_class"),
                cost_basis=acc_config.get("cost_basis"),
                roth_contribution_basis=acc_config.get("roth_contribution_basis", 0.0),
                roth_conversion_basis=acc_config.get("roth_conversion_basis", []),
                roth_first_contribution_year=acc_config.get("roth_first_contribution_year"),
                contribution_caps_by_year={int(k): v for k, v in acc_config.get("contribution_caps_by_year", {}).items()},
                contribution_end_date=date.fromisoformat(acc_config["contribution_end_date"]) if acc_config.get("contribution_end_date") else None,
                return_volatility=acc_config.get("return_volatility"),
                interest_yield=acc_config.get("interest_yield", 0.0),
                capital_gain_yield=acc_config.get("capital_gain_yield", 0.0),
                dividend_yield=acc_config.get("dividend_yield", 0.0),
                qualified_dividend_share=acc_config.get("qualified_dividend_share", 0.0),
                reinvest_distributions=acc_config.get("reinvest_distributions", True),
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
            bond_return_volatility=econ_config.get("bond_return_volatility", 0.06),
            equity_bond_correlation=econ_config.get("equity_bond_correlation", 0.0),
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
                        first_vest_date=date.fromisoformat(g["first_vest_date"]) if g.get("first_vest_date") else None,
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
                tax_deductible=ec.get("tax_deductible", False),
                funding_account=ec.get("funding_account", ""),
                payment_kind=ec.get("payment_kind", "cash"),
                hsa_qualified=ec.get("hsa_qualified", False),
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
                deduction_kind=mc.get("deduction_kind", "none"),
                deductible_debt_limit=mc.get("deductible_debt_limit", 750_000),
                ca_deductible_debt_limit=mc.get("ca_deductible_debt_limit", 1_000_000),
                rate_changes=mc.get("rate_changes", []),
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
                taxable_amount=wf.get("taxable_amount"),
                taxable_kind=wf.get("taxable_kind", "ordinary"),
                wage_owner=wf.get("wage_owner"),
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
                selling_costs=he.get("selling_costs", 0.0),
                purchase_costs=he.get("purchase_costs", 0.0),
                exclusion_eligible=he.get("exclusion_eligible", True),
                mortgage_deduction_kind=he.get("mortgage_deduction_kind", "none"),
                deductible_debt_limit=he.get("deductible_debt_limit", 750_000),
                ca_deductible_debt_limit=he.get("ca_deductible_debt_limit", 1_000_000),
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
        if ss_config is None:
            # Older wizard exports used null for an explicit skip.
            ss_config = {"primary_benefit_at_67": 0, "spouse_benefit_at_67": 0}
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
            surplus_account_id=config.get("surplus_account_id"),
            withdrawal_strategy=config.get("withdrawal_strategy", "fixed"),
            withdrawal_rate=config.get("withdrawal_rate", 0.04),
            survivor_expense_ratio=config.get("survivor_expense_ratio", 0.75),
            monetary_convention=MonetaryConvention(config.get("monetary_convention", "real")),
            start_year=config.get("start_year"),
            balance_date=date.fromisoformat(config["balance_date"]) if config.get("balance_date") else None,
            tax_inputs={int(k): v for k, v in config.get("tax_inputs", {}).items()},
            withdrawal_access_policy=config.get("withdrawal_access_policy", "penalty_free"),
        )

        planner = cls(scenario)
        planner.input_readiness = readiness
        if not readiness["access_assessed"]:
            planner.model_warnings.append("Account access unassessed: total-only savings use an aggregate taxable proxy. Separate account types before relying on early-retirement funding.")
        if readiness["provisional"]:
            planner.model_warnings.append("Provisional inputs: review missing and estimated fields in input_readiness before relying on results.")
        # Optional stress level baked into the config (0..1); CLI --stress
        # overrides it per run.
        planner.stress_level = max(0.0, min(1.0, config.get("stress_level", 0.0)))
        return planner

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
        scenario: str = "mean",
    ) -> float:
        """Compute net growth rate for an account given an allocation.

        Returns: equity_rate * equity_pct + bond_rate * bond_pct,
        minus the account's expense ratio.

        Uses scenario-level capital market assumptions by default.
        If account.growth_rate is set, it overrides the equity rate
        for backward compatibility with legacy configs.
        """
        rates = self.scenario.economic.get_rate(scenario)
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
        net_rate = gross_rate - account.expense_ratio * (1 + inflation if self.scenario.monetary_convention == MonetaryConvention.NOMINAL else 1)
        return net_rate

    def _account_growth_rate(self, account: Account, year: int,
                             rates: Dict) -> float:
        """Deterministic annual growth rate for an account (no volatility).

        Mirrors the Monte Carlo growth step: allocation rates are already
        convention-adjusted inside get_growth_rate_for_allocation; the
        non-allocation rates (real estate, depreciating assets, cash) are
        real and get converted exactly once.
        """
        return self._annual_account_return(account, year, rates.get("scenario", "mean"), rates, 0.0)

    def _liquid_portfolio(self, balances):
        return sum(max(0.0, value) for aid, value in balances.items()
                   if aid in self.accounts and self.accounts[aid].liquid
                   and self.accounts[aid].account_type not in {"real_estate", "vehicle", "529", "hsa"}) + max(0.0, balances.get("_unallocated_cash", 0.0))

    def _account_allocation(self, account: Account, year: int) -> AssetAllocation:
        if account.asset_class == "equity":
            return AssetAllocation(1.0, 0.0)
        if account.asset_class == "bond":
            return AssetAllocation(0.0, 1.0)
        if account.equity_pct is not None:
            return AssetAllocation(account.equity_pct, 1 - account.equity_pct)
        return self.get_equity_allocation(self._account_owner_age(account, year))

    def _annual_account_return(self, account, year, scenario_name, rates,
                               equity_volatility, equity_z=0.0, bond_z=0.0,
                               historical=None):
        inflation = rates["general_inflation"]
        policy = MonetaryPolicy(self.scenario.monetary_convention, self.start_year, inflation)
        # Cash, property and vehicles do not acquire stock-market shocks.
        if account.asset_class == "cash" or account.account_type in {"checking", "cash", "savings", "money_market"}:
            rate = account.growth_rate or 0.0
            return policy.portfolio_return_to_convention(rate - account.expense_ratio, inflation)
        if account.account_type == "real_estate" or account.is_depreciating or account.growth_rate == 0:
            rate = (-0.04 if account.is_depreciating else
                    account.growth_rate if account.growth_rate is not None else
                    rates["housing_appreciation"] if account.account_type == "real_estate" else 0.0)
            return policy.portfolio_return_to_convention(rate, inflation)
        allocation = self._account_allocation(account, year)
        mean = self.get_growth_rate_for_allocation(account, allocation, scenario_name)
        if historical is not None:
            # Historical series supplies EQUITY only; bonds use the configured CMA.
            equity_rate = historical
            if self.scenario.monetary_convention == MonetaryConvention.REAL:
                equity_rate = (1 + historical) / (1 + inflation) - 1
            bond_rate = policy.portfolio_return_to_convention(rates["bond_real_return"], inflation)
            return allocation.equity_pct * equity_rate + allocation.bond_pct * bond_rate - account.expense_ratio * (1 + inflation if self.scenario.monetary_convention == MonetaryConvention.NOMINAL else 1)
        if equity_volatility <= 0:
            return mean
        equity_vol = account.return_volatility if account.return_volatility is not None else equity_volatility
        bond_vol = self.scenario.economic.bond_return_volatility
        shock = allocation.equity_pct * equity_vol * equity_z + allocation.bond_pct * bond_vol * bond_z
        if self.scenario.monetary_convention == MonetaryConvention.NOMINAL:
            shock *= 1 + inflation
        return mean + shock

    def get_account_balance(self, account_id: str, year: int,
                            scenario: str = "mean") -> float:
        """Get projected account balance for a given year (deterministic)."""
        account = self.accounts.get(account_id)
        if not account:
            return 0.0

        years = year - self.start_year
        rates = self.scenario.economic.get_rate(scenario)
        rates["scenario"] = scenario
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
        # Single-household (issue #3): there is no spouse, so any
        # account with owner 'spouse' falls back to the primary. The
        # legacy lookup-by-spouse-name still works because the
        # `owner in {"spouse", spouse_name}` branch only matches when
        # the spouse exists.
        if self.scenario.spouse is None:
            return year - self.scenario.primary.birth_date.year
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
                b / nominal_factor for b in mortgage_balances.values() if b > 0)

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
                self.scenario.spouse.birth_date.year
                if self.scenario.spouse is not None
                else self.scenario.primary.birth_date.year,
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
        wages_by_owner = {}

        for stream in self.scenario.income_streams:
            fraction = _year_active_fraction(
                stream.start_date, stream.end_date, year)
            if fraction <= 0:
                continue
            total_before_stream = total_income
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
                        payment_date = date(year, stream.bonus.payment_month, 1)
                        if stream.start_date <= payment_date < stream.end_date:
                            bonus_growth = stream.bonus.growth_rate
                            stream_income += (stream.bonus.annual
                                              * (1 + bonus_growth) ** years_active)

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
            if stream.is_w2 and not stream.is_passive and not stream.is_ss:
                wages_by_owner[stream.owner] = wages_by_owner.get(stream.owner, 0.0) + total_income - total_before_stream

        return {"total": total_income, "by_source": income_by_source, "wages_by_owner": wages_by_owner}

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
                    status="forecasted" if year > grant_year + 1 else "active",
                    first_vest_date=self._add_months(grant_date, policy.vesting_delay_months),
                )
                total_shares += self._vested_shares_in_year(synthetic_grant, year, equity.end_date)

        return total_shares * equity.current_price

    @staticmethod
    def _add_months(value: date, months: int) -> date:
        import calendar
        n = value.year * 12 + value.month - 1 + months
        year, month0 = divmod(n, 12)
        month = month0 + 1
        return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))

    def _vested_shares_in_year(self, grant, year: int, end_date=None) -> float:
        """How many shares from this grant vest in a given year. Stateless."""
        if grant.status == "cancelled":
            return 0.0
        if grant.cliff_date and end_date and grant.cliff_date >= end_date:
            return 0.0
        if grant.first_vest_date and grant.vesting_pattern in {"quarterly", "monthly"}:
            interval = 3 if grant.vesting_pattern == "quarterly" else 1
            first = grant.first_vest_date
            total = 0.0
            for i in range(16 if interval == 3 else 48):
                vest = self._add_months(first, i * interval)
                if vest.year == year and (end_date is None or vest < end_date):
                    total += max(0.0, min(grant.periodic_shares, grant.total_shares - i * grant.periodic_shares))
            return total
        if end_date and date(year, 1, 1) >= end_date:
            return 0  # employment end is exclusive

        if end_date and end_date.year == year:
            # Dated legacy fallback for an employment-ending year. Explicit schedules win above.
            if grant.vesting_pattern == "cliff_quarterly":
                if grant.cliff_date is None:
                    return 0.0
                first = self._add_months(grant.cliff_date, 3) if grant.cliff_replaces_first_vest else date(grant.cliff_date.year + 1, 1, 1)
                interval = 3
                schedule = [(grant.cliff_date, grant.cliff_shares)]
            else:
                interval = 3 if grant.vesting_pattern == "quarterly" else 1
                first = self._add_months(grant.grant_date, 2 if interval == 3 else 0)
                schedule = []
            schedule += [(self._add_months(first, i * interval), grant.periodic_shares) for i in range(48)]
            vested = 0.0
            in_year = 0.0
            for vest, shares in sorted(schedule):
                actual = min(shares, max(0.0, grant.total_shares - vested))
                vested += actual
                if vest.year == year and vest < end_date:
                    in_year += actual
            return in_year
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
            stress_level: 0.0 = normal, 1.0 = max stress (clamped) —
                discretionary expenses (is_must_spend=False) are cut by
                min_reduction x stress_level. Remaining reduction allowances
                are returned by expense ID for flexible spending strategies.
            mortgage_balances: Optional dict of mortgage.id -> remaining
                balance.  When provided, each year's payment is amortized:
                interest = balance * rate, principal = payment - interest,
                and the dict is updated in place.  Mortgages paid down to
                zero stop generating expenses.  When None, payments are
                modeled flat (legacy behavior).
        """
        stress_level = max(0.0, min(1.0, stress_level))
        total_expenses = 0
        debt_factor = (1 + self.scenario.economic.get_rate(scenario)["general_inflation"]) ** (year - self.start_year)
        expenses_by_category = {}
        mortgage_payments = {}
        expenses_by_id = {}
        planned_by_expense = {}
        reducible_by_expense = {}
        expense_mods = self.calculate_age_events(year)
        mortgage_interest = 0.0
        ca_mortgage_interest = 0.0
        rental_interest = 0.0

        for expense in self.scenario.expenses:
            amount = 0.0
            unreduced_amount = 0.0
            if expense.is_one_time:
                if expense.one_time_date and expense.one_time_date.year == year:
                    amount = expense.one_time_amount
                    unreduced_amount = amount
                    if not expense.is_must_spend:
                        amount *= (1.0 - expense.min_reduction * stress_level)
                    total_expenses += amount
                    expenses_by_category[expense.name] = expenses_by_category.get(expense.name, 0.0) + amount
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

                    unreduced_amount = amount
                    # Apply stress reduction for discretionary expenses
                    if stress_level > 0 and not expense.is_must_spend:
                        reduction = expense.min_reduction * stress_level
                        amount *= (1.0 - reduction)

                    total_expenses += amount
                    expenses_by_category[expense.name] = expenses_by_category.get(expense.name, 0.0) + amount

            expenses_by_id[expense.id] = amount
            planned_by_expense[expense.id] = unreduced_amount
            if amount > 0 and not expense.is_must_spend:
                limit = max(0.0, min(1.0, expense.min_reduction))
                remaining_fraction = 1.0 - limit * stress_level
                # Stress cuts have already spent part of this category's
                # reduction allowance. Do not cut the same dollars twice.
                reducible_by_expense[expense.id] = (
                    amount * limit * (1.0 - stress_level) / remaining_fraction
                    if remaining_fraction > 0 else 0.0)

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
                    end = mortgage.end_date
                    for event in self.scenario.housing_events:
                        if event.sale_price > 0 and event.property_id == mortgage.property_id:
                            end = min(end, event.event_date)
                    fraction = _year_active_fraction(mortgage.start_date, end, year)
                    amount = 0.0
                    months = round(12 * fraction)
                    first_month = max(1, mortgage.start_date.month if mortgage.start_date.year == year else 1)
                    for month in range(first_month, first_month + months):
                        rate, monthly_payment = mortgage.interest_rate, mortgage.monthly_payment
                        for change in sorted(mortgage.rate_changes, key=lambda c: c["date"]):
                            if date.fromisoformat(change["date"]) <= date(year, min(month, 12), 1):
                                rate = change.get("interest_rate", rate)
                                monthly_payment = change.get("monthly_payment", monthly_payment)
                        monthly_rate = rate / 12
                        if balance <= 0:
                            break
                        interest = balance * monthly_rate
                        payment = min(
                            monthly_payment, balance + interest)
                        if mortgage.deduction_kind == "itemized":
                            mortgage_interest += interest * min(1.0, mortgage.deductible_debt_limit / balance)
                            ca_mortgage_interest += interest * min(1.0, mortgage.ca_deductible_debt_limit / balance)
                        elif mortgage.deduction_kind == "rental":
                            rental_interest += interest
                        balance -= payment - interest
                        amount += payment
                    mortgage_balances[mortgage.id] = max(0.0, balance)
                else:
                    amount = mortgage.monthly_payment * 12 * _year_active_fraction(
                        mortgage.start_date, mortgage.end_date, year)
                amount /= debt_factor
                total_expenses += amount
                expenses_by_category[f"Mortgage - {mortgage.name}"] = expenses_by_category.get(f"Mortgage - {mortgage.name}", 0.0) + amount
                mortgage_payments[f"Mortgage - {mortgage.name}"] = mortgage_payments.get(f"Mortgage - {mortgage.name}", 0.0) + amount

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
                origin = next((he for he in self.scenario.housing_events if (he.new_mortgage_id or f"{he.id}_mortgage") == mort_id), None)
                for _ in range(months):
                    if balance <= 0:
                        break
                    interest = balance * monthly_rate
                    if origin and origin.mortgage_deduction_kind == "itemized":
                        mortgage_interest += interest * min(1.0, origin.deductible_debt_limit / balance)
                        ca_mortgage_interest += interest * min(1.0, origin.ca_deductible_debt_limit / balance)
                    elif origin and origin.mortgage_deduction_kind == "rental":
                        rental_interest += interest
                    pmt = min(payment, balance + interest)
                    balance -= pmt - interest
                    amount += pmt
                mortgage_balances[mort_id] = max(0.0, balance)
                if amount > 0:
                    amount /= debt_factor
                    total_expenses += amount
                    expenses_by_category[f"Mortgage - {mort_id}"] = expenses_by_category.get(f"Mortgage - {mort_id}", 0.0) + amount
                    mortgage_payments[f"Mortgage - {mort_id}"] = amount

        return {"total": total_expenses, "by_category": expenses_by_category, "by_expense": expenses_by_id, "mortgage_payments": mortgage_payments, "planned_by_expense": planned_by_expense, "reducible_by_expense": reducible_by_expense, "mortgage_interest": mortgage_interest / debt_factor, "ca_mortgage_interest": ca_mortgage_interest / debt_factor, "rental_interest": rental_interest / debt_factor}

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
        # Issue #3: single-household plans have no spouse; the
        # younger-age trigger is the primary's age.
        if self.scenario.spouse is None:
            spouse_age = primary_age
        else:
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
        mortgage_interest: float = 0.0,
        ca_mortgage_interest: Optional[float] = None,
        ca_property_tax: float = 0.0,
        ca_income_adjustment: float = 0.0,
        charitable_limit_pct: float = 0.6,
        wages_by_owner: Optional[dict] = None,
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

        # Only an actual QCD is excluded. Charitable intent alone cannot create one.
        ordinary_for_tax = max(0.0, income.ordinary - qcd_amount)
        capital_gains = max(0.0, income.capital_gains) + income.qualified_dividends
        if income.capital_gains < 0:
            ordinary_for_tax = max(0.0, ordinary_for_tax + max(income.capital_gains, -1500 if status == FilingStatus.MFS else -3000))
        magi = ordinary_for_tax + capital_gains
        salt_cap = law.salt_cap if law.salt_cap is not None else float('inf')
        salt_start = law.salt_phaseout_start
        floor = law.salt_floor
        if status == FilingStatus.MFS:
            salt_cap /= 2
            floor /= 2
            if salt_start is not None:
                salt_start /= 2
        if salt_start is not None:
            salt_cap = max(floor, salt_cap - .30 * max(0.0, magi - salt_start))
        salt_deduction = min(max(0.0, salt_paid), salt_cap)
        charitable = min(max(0.0, charitable_deductions), max(0.0, magi * charitable_limit_pct))
        charitable = max(0.0, charitable - law.charitable_deduction_floor_pct * magi)
        itemized = salt_deduction + charitable + mortgage_interest
        top_threshold = law.federal_brackets[status][-2].upper
        itemized -= law.itemized_reduction_rate * min(itemized, max(0.0, magi - top_threshold))
        deduction = max(law.standard_deduction.get(status, 29_200), itemized)
        # A deduction remaining after ordinary income also shelters preferential gains.
        ordinary_after_deduction = max(0.0, ordinary_for_tax - deduction)
        gain_after_deduction = max(0.0, capital_gains - max(0.0, deduction - ordinary_for_tax))
        federal_ordinary = bracket_tax(ordinary_after_deduction, law.federal_brackets.get(status, []))
        cg_brackets = law.ltcg_brackets.get(status, [])
        ltcg_tax = bracket_tax(ordinary_after_deduction + gain_after_deduction, cg_brackets) - bracket_tax(ordinary_after_deduction, cg_brackets)
        regular_tax = federal_ordinary + ltcg_tax
        from .tax_law import calculate_niit, calculate_amt, calculate_child_tax_credit
        # SALT and the standard deduction are AMT addbacks; qualified mortgage/gifts remain deductible.
        amt = calculate_amt(regular_tax, max(0.0, ordinary_for_tax - charitable - mortgage_interest), max(0.0, capital_gains - max(0.0, charitable + mortgage_interest - ordinary_for_tax)), law, status)
        federal_tax = max(0.0, regular_tax + amt - calculate_child_tax_credit(num_children, magi, law, status))
        federal_tax += calculate_niit(max(0.0, income.capital_gains + income.qualified_dividends + income.investment_ordinary), magi, law, status)
        ca_tax = 0.0
        if str(getattr(self.scenario, "state", "CA")).upper() == "CA":
            ca_total = max(0.0, ordinary_for_tax + capital_gains + ca_income_adjustment)
            ca_gifts = min(max(0.0, charitable_deductions), .5 * ca_total)
            ca_itemized = ca_property_tax + ca_gifts + (mortgage_interest if ca_mortgage_interest is None else ca_mortgage_interest)
            ca_start = law.ca_itemized_phaseout_start.get(status, float('inf'))
            ca_itemized -= min(.8 * ca_itemized, .06 * max(0.0, magi - ca_start))
            ca_deduction = max(law.ca_standard_deduction.get(status, 0.0), ca_itemized)
            ca_taxable = max(0.0, ca_total - ca_deduction)
            ca_tax = bracket_tax(ca_taxable, law.ca_brackets_by_status.get(status, law.ca_brackets))
            ca_tax += .01 * max(0.0, ca_taxable - 1_000_000)
        payroll_tax = 0.0
        if wages_by_owner:
            wages = [max(0.0, amount) for amount in wages_by_owner.values()]
            payroll_tax = sum(.062 * min(amount, law.social_security_wage_base) + .0145 * amount for amount in wages)
            threshold = 250_000 if status == FilingStatus.MFJ else 125_000 if status == FilingStatus.MFS else 200_000
            payroll_tax += .009 * max(0.0, sum(wages) - threshold)
        return federal_tax + ca_tax + payroll_tax

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
        return date(year, 1, 1) >= person.retirement_date

    # ------------------------------------------------------------------
    # Withdrawal strategy methods
    # ------------------------------------------------------------------
    def _minimum_spending(self, year: int, base_spending: float, expenses: Dict) -> float:
        """Protect obligations and the uncut portion of discretionary costs.

        The simulation supplies a cash floor after funding-account debits,
        survivor scaling, medical inflation and IRMAA. Direct strategy calls
        derive the reduction budget from current-year expense amounts.
        """
        if "spending_floor" in expenses:
            return max(0.0, min(base_spending, expenses["spending_floor"]))
        budget = expenses.get("reducible_by_expense")
        if budget is None:
            budget = self.calculate_annual_expenses(year)["reducible_by_expense"]
        policy = MonetaryPolicy(self.scenario.monetary_convention, self.start_year,
                                self.scenario.economic.general_inflation)
        reducible = policy.adjust_for_inflation(sum(budget.values()), year)
        return max(0.0, base_spending - reducible)

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

        adjusted = max(self._minimum_spending(year, base_spending, expenses), adjusted)

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
        inflation = self.scenario.economic.general_inflation
        starting_portfolio = getattr(self, '_starting_portfolio', portfolio_value)
        planned_portfolio = starting_portfolio
        if self.scenario.monetary_convention == MonetaryConvention.NOMINAL:
            planned_portfolio *= (1 + inflation) ** years_from_start

        if strategy == 'fixed':
            return base_spending

        elif strategy == 'guardrails':
            return max(
                self._minimum_spending(year, base_spending, expenses),
                self.apply_guardrails(
                    year, base_spending, portfolio_value, planned_portfolio),
            )

        elif strategy == 'dynamic':
            return self.apply_dynamic_spending(
                year, base_spending, portfolio_value, expenses,
            )

        elif strategy == 'percent_of_portfolio':
            floor = self._minimum_spending(year, base_spending, expenses)
            withdrawal_rate = getattr(self.scenario, 'withdrawal_rate', 0.04)
            return self.apply_percent_of_portfolio(
                year, portfolio_value, withdrawal_rate, floor,
            )

        elif strategy == 'floor_ceiling':
            floor = self._minimum_spending(year, base_spending, expenses)
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
        stress_level: Optional[float] = None,
        stochastic: bool = False,
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
        from .outcomes import OutcomeTracker
        access_assessed = (self.input_readiness["access_assessed"]
                           and self.scenario.withdrawal_access_policy == "penalty_free")
        outcome_tracker = OutcomeTracker(access_assessed)
        years_with_spending_cuts = 0
        maximum_spending_cut_fraction = 0.0
        total_taxes = 0.0
        total_ss = 0.0
        total_contributions = 0.0
        total_aca_subsidy = 0.0
        total_aca_subsidy_estimate = 0.0
        total_estate_tax = 0.0
        peak_nw = 0.0
        out_of_savings_year = None
        access_shortfall_year = None
        portfolio_depletion_year = None
        net_worth_by_year: Dict[int, float] = {}
        projections = [] if collect_projections else None
        # Stress level: 0 = normal, 1 = max discretionary cuts
        # (None → planner-level default set via CLI --stress).
        if stress_level is None:
            stress_level = getattr(self, "stress_level", 0.0)
        stress_level = max(0.0, min(1.0, stress_level))

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

        # Use supplied aggregate basis; missing basis retains the legacy balance assumption.
        cost_basis = CostBasisTracker()
        for account_id, account in self.accounts.items():
            if account.tax_treatment == "taxable":
                cost_basis.set_basis(account_id, account.cost_basis if account.cost_basis is not None else account.balance)


        rates = self.scenario.economic.get_rate(scenario_name)
        rates["scenario"] = scenario_name
        inflation_rate = rates["general_inflation"]
        run_accounts = dict(self.accounts)
        surplus_destination = self.scenario.surplus_account_id
        if surplus_destination is None:
            surplus_destination = next((aid for aid, a in run_accounts.items() if a.liquid and a.account_type == "checking"), None)
        if surplus_destination is None:
            surplus_destination = next((aid for aid, a in run_accounts.items() if a.liquid and a.tax_treatment == "taxable" and a.account_type not in {"real_estate", "vehicle", "hsa", "529"}), None)
        if surplus_destination is None:
            surplus_destination = "_unallocated_cash"
            run_accounts[surplus_destination] = Account(surplus_destination, "Unallocated cash", "checking", "taxable", 0, growth_rate=0, asset_class="cash")
            balances[surplus_destination] = 0.0
            cost_basis.set_basis(surplus_destination, 0.0)
        birth_dates = {"primary": self.scenario.primary.birth_date}
        if self.scenario.spouse:
            birth_dates["spouse"] = self.scenario.spouse.birth_date
        withdrawal_engine = WithdrawalEngine(
            run_accounts, cost_basis, self.scenario.withdrawal_access_policy,
            birth_dates, self.start_year)
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
        self._starting_portfolio = self._liquid_portfolio(balances)

        # Historical return sequence index (for sequential replay)
        _hist_idx = 0

        # Local ownership map for the spousal rollover (R7).  Mutated only in
        # this run's local state, never the shared Account objects, so Monte
        # Carlo iterations stay isolated.
        owner_map: Dict[str, str] = {
            aid: (acc.owner or "primary").lower()
            for aid, acc in self.accounts.items()}
        rollover_done = False

        # --- Stochastic mortality (optional) ---
        # Sample ONE household death age from the SSA 2023 tables; both
        # spouses die together at that year (simplification). The run ends
        # once the sampled age is passed. Deterministic (stochastic=False)
        # keeps the configured-longevity horizon below.
        stochastic_death_age = None
        if stochastic:
            _mm = MortalityModel()
            stochastic_death_age = _mm.sample_death_age(
                self.start_year - self.scenario.primary.birth_date.year,
                is_male=_mm.primary_male,
                rng=rng,
            )

        # Run until the LAST death: the younger/longer-lived person sets
        # the horizon (estate tax is assessed when both are gone). In
        # stochastic mode the horizon is the single sampled death year.
        # Issue #3: when spouse is None (single-household), the horizon
        # is the primary's death year + 1 alone.
        primary_death_year = (
            self.scenario.primary.birth_date.year
            + self.scenario.primary.longevity_age
        )
        spouse_death_year = (
            self.scenario.spouse.birth_date.year
            + self.scenario.spouse.longevity_age
            if self.scenario.spouse is not None
            else primary_death_year
        )
        max_year = (
            self.scenario.primary.birth_date.year + stochastic_death_age + 1
            if stochastic and stochastic_death_age is not None
            else max(primary_death_year, spouse_death_year) + 1
        )

        for year in range(self.start_year, max_year):
            # Single-household: treat spouse as having the same birth year
            # as the primary so the context (ages, survivor state) stays
            # well-defined. The if-sentinel downstream keys off the
            # presence of scenario.spouse, not these values.
            spouse_birth_year = (
                self.scenario.spouse.birth_date.year
                if self.scenario.spouse is not None
                else self.scenario.primary.birth_date.year
            )
            context = make_year_context(
                year, self.start_year,
                self.scenario.primary.birth_date.year,
                spouse_birth_year,
            )
            primary_age = context.primary_age
            spouse_age = context.spouse_age
            younger_age = context.younger_age
            years_from_base = context.years_from_base
            yearly_state = make_state(context, balances, mortgage_balances)

            # --- Filing status (KTD1/KTD8) ---
            # One longevity-derived survivor snapshot per year, shared with
            # Monte Carlo. Normalize to the FilingStatus enum before every
            # tax call so brackets/deductions resolve correctly.
            if stochastic:
                # Simplified "both die together" model: the household stays
                # MFJ (both alive) until the single sampled death year, then
                # the run ends. No survivor transitions, rollover, or estate.
                snap = stochastic_alive_snapshot(
                    year,
                    self.scenario.dependents,
                    primary_age,
                    spouse_age,
                    spouse_present=self.scenario.spouse is not None,
                )
                filing_status = normalize_filing_status(snap.filing_status)
            else:
                snap = survivor_snapshot(
                    year, self.scenario.primary, self.scenario.spouse,
                    self.scenario.dependents,
                )
                filing_status = normalize_filing_status(snap.filing_status)

                # Spousal rollover (R7): at the first death, reassign eligible
                # pre-tax account ownership to the survivor in local state only.
                if snap.survivor is not None and not rollover_done:
                    deceased = ("spouse" if snap.survivor == "primary"
                                else "primary")
                    rollover_pretax_ownership(
                        owner_map, self.accounts, deceased, snap.survivor)
                    rollover_done = True

            # Get tax law for this year
            law = tax_law_registry.law_for_year(year)

            if stochastic:
                if primary_age > stochastic_death_age:
                    break
            elif (
                primary_age > self.scenario.primary.longevity_age
                and (
                    self.scenario.spouse is None
                    or spouse_age > self.scenario.spouse.longevity_age
                )
            ):
                break

            nominal_factor = monetary_policy.to_nominal_for_tax(1.0, year)
            withdrawal_engine.nominal_factor = nominal_factor
            if self.scenario.monetary_convention == MonetaryConvention.REAL and year > self.start_year:
                for aid in cost_basis.basis_by_account:
                    cost_basis.basis_by_account[aid] /= (1 + inflation_rate)
            rmd_factor = (1 + inflation_rate) if self.scenario.monetary_convention == MonetaryConvention.REAL and year > self.start_year else 1.0
            withdrawal_engine.rmd_reference_balances = {aid: value / rmd_factor for aid, value in balances.items()}
            withdrawal_engine.rmd_year = year
            taxable_cash_opening = sum(max(0.0, balances.get(aid, 0.0)) for aid, a in run_accounts.items()
                if a.liquid and a.tax_treatment == "taxable" and a.account_type not in {"real_estate", "vehicle", "hsa", "529"})
            # Shared equity/bond shocks preserve common market risk across accounts.
            generator = rng if rng is not None else np.random.default_rng()
            equity_z, independent_bond_z = generator.normal(size=2) if return_volatility > 0 else (0.0, 0.0)
            rho = self.scenario.economic.equity_bond_correlation
            bond_z = rho * equity_z + math.sqrt(max(0.0, 1 - rho * rho)) * independent_bond_z
            historical = (self._historical_return_override[_hist_idx]
                          if self._historical_return_override is not None
                          and _hist_idx < len(self._historical_return_override) else None)
            investment_ordinary = investment_qualified = investment_cash = investment_capital_gains = 0.0
            investment_by_account = {}
            from .investment_income import distribute
            for account_id in list(balances):
                account = run_accounts.get(account_id)
                if account is None or balances[account_id] <= 0:
                    continue
                actual_rate = self._annual_account_return(
                    account, year, scenario_name, rates, return_volatility,
                    equity_z, bond_z, historical)
                # The base row uses price index 1, just like its income,
                # expenses and tax conversions. Later rows advance the index.
                if self.scenario.monetary_convention == MonetaryConvention.NOMINAL and year == self.start_year:
                    actual_rate = (1.0 + actual_rate) / (1.0 + inflation_rate) - 1.0
                opening = balances[account_id]
                balances[account_id] *= max(0.0, 1.0 + actual_rate)
                balance, basis, ordinary_dist, qualified_dist, cash_dist, gain_dist = distribute(
                    account, opening, balances[account_id], cost_basis.get_basis(account_id, 0.0), rmd_factor)
                balances[account_id] = balance
                cost_basis.set_basis(account_id, basis)
                investment_ordinary += ordinary_dist
                investment_qualified += qualified_dist
                investment_cash += cash_dist
                investment_capital_gains += gain_dist
                if ordinary_dist + qualified_dist + gain_dist > 0:
                    investment_by_account[account_id] = {"ordinary": ordinary_dist, "qualified_dividends": qualified_dist, "capital_gains": gain_dist, "cash": cash_dist, "reinvested": ordinary_dist + qualified_dist + gain_dist - cash_dist}

            # Advance historical return index (one position per simulated year)
            if self._historical_return_override is not None:
                _hist_idx += 1

            # --- Step 2: Retirement status (used below) ---
            primary_retired = self._is_retired(year, self.scenario.primary)
            # Issue #3: spouse is optional. Single-household: there is
            # no spouse, so the spouse is treated as already retired
            # (no further spousal income, no SS spousal benefit).
            if self.scenario.spouse is None:
                spouse_retired = True
            else:
                spouse_retired = self._is_retired(year, self.scenario.spouse)

            # --- Step 3: Income ---
            income_data = self.calculate_annual_income(year, scenario_name)
            annual_income = income_data["total"]

            # In NOMINAL mode, inflate income to year-of dollars
            annual_income = monetary_policy.adjust_for_inflation(
                annual_income, year, inflation_rate,
            )

            annual_income += investment_cash

            # Social Security (R4): claimed-benefit-only survivor benefit.
            # The death year retains both payable benefits; after a death
            # the survivor receives the higher of their own and the
            # deceased person's payable benefit — no benefit is invented
            # for an unclaimed deceased spouse.
            ss_primary_annual = (
                self.calculate_social_security(year, self.scenario.primary)
                if primary_age >= self.scenario.social_security.primary_claiming_age
                else 0.0)
            # Issue #3: spouse is optional. Single-household plans
            # have no spousal SS benefit to compute.
            if self.scenario.spouse is None:
                ss_spouse_annual = 0.0
            else:
                ss_spouse_annual = (
                    self.calculate_social_security(year, self.scenario.spouse)
                    if spouse_age >= self.scenario.social_security.spouse_claiming_age
                    else 0.0)
            ss_income = compute_survivor_ss_benefit(
                ss_primary_annual, ss_spouse_annual,
                snap.primary_alive, snap.spouse_alive)
            # In NOMINAL mode, inflate SS (it already has COLA but
            # we need the base-year → year inflation for convention)
            ss_income = monetary_policy.adjust_for_inflation(
                ss_income, year, inflation_rate,
            )
            annual_income += ss_income
            total_ss += ss_income

            # --- Step 4: Expenses ---
            expense_data = self.calculate_annual_expenses(
                year, scenario_name, stress_level=stress_level,
                mortgage_balances=mortgage_balances,
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

            survivor_expense_ratio = self.scenario.survivor_expense_ratio if snap.survivor is not None else 1.0
            annual_expenses *= survivor_expense_ratio
            # --- Step 4b: IRMAA Medicare surcharges (per-person) ---
            # 2-year lookback: use MAGI from 2 years prior
            lookback_year = year - 2
            magi_2yr_ago = magi_history.get(lookback_year, 0.0)

            # Medicare-covered adults: living adults at Medicare age (R5/KTD5).
            num_medicare = snap.medicare_adult_count

            irmaa_amount = 0.0
            if num_medicare > 0:
                # IRS uses combined household MAGI for IRMAA tiers
                irmaa_amount = monetary_policy.from_nominal_after_tax(
                    tax_law_irmaa(magi_2yr_ago, law, num_people=num_medicare), year)
                annual_expenses += irmaa_amount

            # --- Step 4c: ACA subsidy (per-person, pre-Medicare) ---
            # The subsidy depends on MAGI, which includes withdrawal
            # income, so it is recomputed inside the fixed-point loop
            # below rather than here.  ACA family size uses the survivor
            # definition: living adults plus active dependents (R5/KTD5).
            aca_family_size = snap.aca_family_size

            # Resolve the strategy into actual expense IDs before any payment
            # or tax deduction. Obligations and exhausted allowances stay fixed.
            from .spending import realize_spending
            scaled = lambda value: monetary_policy.adjust_for_inflation(value, year, inflation_rate) * survivor_expense_ratio
            planned_by_expense = {key: scaled(value) for key, value in expense_data["by_expense"].items()}
            obligations = max(0.0, annual_expenses - sum(planned_by_expense.values()))
            planned_by_expense["__obligations"] = obligations
            allowances = {key: scaled(value) for key, value in expense_data["reducible_by_expense"].items()}
            expense_data["spending_floor"] = max(0.0, annual_expenses - sum(allowances.values()))
            planned_spending = annual_expenses + sum(scaled(expense_data["planned_by_expense"][key] - value) for key, value in expense_data["by_expense"].items())
            target = annual_expenses
            if primary_retired and spouse_retired:
                target = self.apply_withdrawal_strategy(
                    year, annual_expenses, self._liquid_portfolio(balances), portfolio_peak, expense_data)
            actual_by_expense = realize_spending(planned_by_expense, allowances, target)
            annual_expenses = sum(actual_by_expense.values())
            spending_cut = max(0.0, planned_spending - annual_expenses)
            # Rebuild named categories from actual expense IDs (duplicate names
            # aggregate for reporting, while funding and deductions stay per ID).
            category_amounts = {}
            for expense in self.scenario.expenses:
                category_amounts[expense.name] = category_amounts.get(expense.name, 0.0) + actual_by_expense.get(expense.id, 0.0)
            for key, value in expense_data["mortgage_payments"].items():
                category_amounts[key] = category_amounts.get(key, 0.0) + scaled(value)
            remainder = annual_expenses - sum(category_amounts.values())
            if abs(remainder) > 1e-7:
                category_amounts["Medical inflation, IRMAA and strategy adjustments"] = category_amounts.get("Medical inflation, IRMAA and strategy adjustments", 0.0) + remainder
            expense_data["by_category"] = category_amounts
            expense_data["actual_by_expense"] = actual_by_expense
            funded_expenses = 0.0
            funded_capital_gains = 0.0
            funded_by_expense = {}
            for expense in self.scenario.expenses:
                if not expense.funding_account or expense.id not in actual_by_expense:
                    continue
                aid = expense.funding_account
                source_account = run_accounts[aid]
                if source_account.account_type == "hsa" and not expense.hsa_qualified:
                    continue
                if source_account.tax_treatment in {"pre_tax", "roth"}:
                    continue
                requested = actual_by_expense[expense.id]
                available = max(0.0, balances.get(aid, 0.0))
                funded = min(available, requested)
                if available > 0:
                    used_basis = cost_basis.debit_basis(aid, cost_basis.get_basis(aid, 0.0) * funded / available)
                    if (source_account.tax_treatment == "taxable" and expense.payment_kind != "in_kind"
                            and source_account.account_type not in {"checking", "cash", "savings", "money_market"}):
                        funded_capital_gains += funded - used_basis
                balances[aid] -= funded
                funded_expenses += funded
                funded_by_expense[expense.id] = funded
            annual_expenses -= funded_expenses
            # --- Step 4f: Pre-tax rollovers (e.g. 401k -> trad IRA) ---
            # Complete rollovers before same-year conversions.
            for ro in self.scenario.rollover_events:
                if ro.event_date.year != year:
                    continue
                source = balances.get(ro.source_account, 0.0)
                if source <= 0:
                    continue
                withdrawal_engine.rmd_reference_balances[ro.target_account] = withdrawal_engine.rmd_reference_balances.get(ro.target_account, 0.0) + withdrawal_engine.rmd_reference_balances.get(ro.source_account, 0.0)
                withdrawal_engine.rmd_reference_balances[ro.source_account] = 0.0
                balances[ro.source_account] = 0.0
                balances[ro.target_account] = (
                    balances.get(ro.target_account, 0.0) + source)
                # Pre-tax -> pre-tax: no basis change

            # --- Step 4e: Roth conversions ---
            # Reserve each account's RMD before converting; an RMD cannot be converted.
            reserves = {}
            for aid, account in self.accounts.items():
                age = spouse_age if owner_map[aid] == "spouse" else primary_age
                birth_year = year - age
                start_age = 75 if birth_year >= 1960 else 73 if birth_year >= 1951 else 72 if birth_year >= 1949 else 70.5
                if account.tax_treatment == "pre_tax" and age >= start_age:
                    reserves[aid] = withdrawal_engine.rmd_reference_balances.get(aid, 0.0) / _rmd_divisor(age)
            rc_result = process_roth_conversions(
                [replace(rc, annual_amount=monetary_policy.adjust_for_inflation(rc.annual_amount, year))
                 for rc in self.scenario.roth_conversions], year, balances, rmd_reserves=reserves)
            for conversion in rc_result.conversions:
                target = run_accounts[conversion["target"]]
                owner = owner_map.get(target.id, (target.owner or "primary").lower())
                if target.account_type == "roth_ira":
                    withdrawal_engine.access.add_conversion(owner, conversion["amount"] * nominal_factor, year)
            if rc_result.total_converted > 0:
                # Track for later use when building ordinary income
                _roth_conversion_income = rc_result.ordinary_income_added
            else:
                _roth_conversion_income = 0.0

            wage_events = {}
            event_ordinary = 0.0
            event_capital_gains = funded_capital_gains + investment_capital_gains
            for windfall in self.scenario.windfalls:
                if windfall.date.year != year:
                    continue
                target = windfall.goes_to_account
                if not target or target not in balances:
                    continue
                amount = monetary_policy.adjust_for_inflation(windfall.amount, year)
                if windfall.source_account:
                    source = windfall.source_account
                    available = max(0.0, balances.get(source, 0.0))
                    amount = min(amount, available)
                    basis_moved = cost_basis.debit_basis(source, cost_basis.get_basis(source, 0.0) * amount / available) if available else 0.0
                    balances[source] -= amount
                else:
                    basis_moved = amount
                balances[target] += amount
                if self.accounts[target].tax_treatment == "taxable":
                    cost_basis.set_basis(target, cost_basis.get_basis(target, 0.0) + basis_moved)
                # Transfers do not create income merely because cash changes account.
                taxable = windfall.taxable_amount
                if taxable is None:
                    taxable = windfall.amount if windfall.is_taxable and not windfall.source_account else 0.0
                taxable = monetary_policy.adjust_for_inflation(taxable, year)
                if windfall.wage_owner:
                    wage_events[windfall.wage_owner] = wage_events.get(windfall.wage_owner, 0.0) + taxable
                if windfall.taxable_kind == "capital_gains":
                    event_capital_gains += taxable
                else:
                    event_ordinary += taxable
            housing_shortfall = 0.0
            created_mortgages = set()
            for he in self.scenario.housing_events:
                mortgages_before_event = set(mortgage_balances)
                # Housing inputs are base-year purchasing-power amounts;
                # loan contracts and statutory gain exclusions are nominal.
                event_factor = monetary_policy.inflation_factor(year)
                nominal_event = replace(he, **{key: getattr(he, key) * event_factor for key in (
                    "sale_price", "purchase_price", "down_payment", "mortgage_amount",
                    "selling_costs", "purchase_costs")})
                nominal_balances = {aid: amount * nominal_factor for aid, amount in balances.items()}
                before_event = dict(nominal_balances)
                he_result = process_housing_event(
                    nominal_event, year, nominal_balances, mortgage_balances,
                    cost_basis=cost_basis.get_basis(he.property_id or "real_estate", 0.0) * nominal_factor,
                    filing_status=filing_status.value, state=self.scenario.state,
                    mortgage_property_map=mortgage_property_map,
                    event_mortgage_terms=event_mortgage_terms, defer_tax=True)
                balances.clear()
                balances.update({aid: amount / nominal_factor for aid, amount in nominal_balances.items()})
                created_mortgages.update(set(mortgage_balances) - mortgages_before_event)
                event_capital_gains += he_result.taxable_gain / nominal_factor
                housing_shortfall += he_result.funding_shortfall / nominal_factor
                if he_result.event_type != "none":
                    destination = he.goes_to_account or "joint_brokerage"
                    if he_result.sale_proceeds > 0 and destination in run_accounts and run_accounts[destination].tax_treatment == "taxable":
                        cost_basis.set_basis(destination, cost_basis.get_basis(destination) + he_result.sale_proceeds / nominal_factor)
                    funding = he.funding_account or "joint_brokerage"
                    available = max(0.0, before_event.get(funding, 0.0) + (he_result.sale_proceeds if funding == destination else 0.0)) / nominal_factor
                    paid = min(available, he_result.purchase_funding / nominal_factor)
                    if paid > 0:
                        used_basis = cost_basis.debit_basis(funding, cost_basis.get_basis(funding) * paid / available)
                        if run_accounts[funding].account_type not in {"checking", "cash", "savings", "money_market"}:
                            event_capital_gains += paid - used_basis
                    property_id = he.property_id or f"property_{he.id}"
                    if he.purchase_price > 0 and property_id not in run_accounts:
                        run_accounts[property_id] = Account(property_id, "Purchased property", "real_estate", "taxable", 0.0, liquid=False)
                    cost_basis.set_basis(property_id,
                        (nominal_event.purchase_price + nominal_event.purchase_costs) / nominal_factor if he.purchase_price > 0 else 0.0)
            # Newly originated loans make their first payments in the purchase year,
            # without amortizing existing loans or charging living expenses twice.
            if created_mortgages:
                new_balances = {aid: mortgage_balances[aid] for aid in created_mortgages}
                new_terms = {aid: event_mortgage_terms[aid] for aid in created_mortgages if aid in event_mortgage_terms}
                new_expenses = self.calculate_annual_expenses(year, scenario_name, mortgage_balances=new_balances, event_mortgage_terms=new_terms)
                for aid in created_mortgages:
                    key = f"Mortgage - {aid}"
                    payment = new_expenses["by_category"].get(key, 0.0)
                    active_payment = monetary_policy.adjust_for_inflation(payment, year)
                    annual_expenses += active_payment
                    planned_spending += active_payment
                    actual_by_expense["__new_mortgage:" + aid] = active_payment
                    expense_data["by_category"][key] = expense_data["by_category"].get(key, 0.0) + active_payment
                mortgage_balances.update(new_balances)
                for field in ("mortgage_interest", "ca_mortgage_interest", "rental_interest"):
                    expense_data[field] += new_expenses.get(field, 0.0)
            if housing_shortfall > 1 and out_of_savings_year is None:
                out_of_savings_year = year

            outcome_tolerance = monetary_policy.adjust_for_inflation(1.0, year, inflation_rate)
            if spending_cut > outcome_tolerance:
                years_with_spending_cuts += 1
                maximum_spending_cut_fraction = max(maximum_spending_cut_fraction, spending_cut / planned_spending)

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
            trial_magi = annual_income - investment_cash + investment_ordinary + investment_qualified + investment_capital_gains  # withdrawal-inclusive MAGI
            converged = False
            taxes = 0.0
            aca_subsidy = 0.0
            new_needed = 0.0
            tax_ordinary_nominal = 0.0
            tax_cg_nominal = 0.0
            active_owners = {owner for owner, retired in (("primary", primary_retired), ("spouse", spouse_retired)) if not retired}
            ages = {"primary": primary_age, "spouse": spouse_age}
            wages_for_tax = {owner: monetary_policy.to_nominal_for_tax(monetary_policy.adjust_for_inflation(value, year), year) for owner, value in income_data.get("wages_by_owner", {}).items()}
            for owner, value in wage_events.items():
                wages_for_tax[owner] = wages_for_tax.get(owner, 0.0) + monetary_policy.to_nominal_for_tax(value, year)
            wages_active = {owner: monetary_policy.adjust_for_inflation(value, year) for owner, value in income_data.get("wages_by_owner", {}).items()}
            cap_factor = monetary_policy.inflation_factor(year) if self.scenario.monetary_convention == MonetaryConvention.REAL else 1.0
            tax_options = dict(self.scenario.tax_inputs.get(year, {}))
            for key in ("salt_paid", "charitable_deductions", "mortgage_interest", "ca_mortgage_interest", "ca_property_tax", "ca_income_adjustment"):
                if key in tax_options:
                    tax_options[key] = monetary_policy.to_nominal_for_tax(tax_options[key], year)
            qualified_giving = sum(actual_by_expense.get(e.id, 0.0) for e in self.scenario.expenses if e.tax_deductible and e.category == "charity")
            tax_options.setdefault("charitable_deductions", monetary_policy.to_nominal_for_tax(qualified_giving, year))
            tax_options.setdefault("mortgage_interest", monetary_policy.to_nominal_for_tax(monetary_policy.adjust_for_inflation(expense_data.get("mortgage_interest", 0.0), year), year))
            tax_options.setdefault("ca_mortgage_interest", monetary_policy.to_nominal_for_tax(monetary_policy.adjust_for_inflation(expense_data.get("ca_mortgage_interest", 0.0), year), year))
            subsidy_used = 0.0
            for _ in range(40):
                old_tax = taxes
                contribution_basis = dict(cost_basis.basis_by_account)
                contribution_access = withdrawal_engine.access.snapshot()
                preview = withdrawal_engine.contribute(dict(balances), max(0.0, annual_income - annual_expenses + subsidy_used - taxes), year, active_owners, ages, wages_active, cap_factor) if active_owners else {}
                cost_basis.basis_by_account.clear()
                cost_basis.basis_by_account.update(contribution_basis)
                withdrawal_engine.access.restore(contribution_access)
                def employee_amount(aid, total):
                    a = self.accounts[aid]
                    if a.employer_match <= 0:
                        return total
                    uncapped = total / (1 + a.employer_match)
                    return max(uncapped, total - a.employer_match * a.employer_match_limit) if a.employer_match_limit > 0 else uncapped
                pretax_deduction = sum(employee_amount(aid, total) for aid, total in preview.items() if self.accounts[aid].tax_treatment == "pre_tax" and self.accounts[aid].account_type in {"401k", "trad_401k"})
                hsa_deduction = sum(employee_amount(aid, total) for aid, total in preview.items() if self.accounts[aid].account_type == "hsa")
                trial_balances = dict(balances)
                basis_snapshot = dict(cost_basis.basis_by_account)
                access_snapshot = withdrawal_engine.access.snapshot()
                # Always execute (even at needed=0) so the forced RMD
                # floor is part of the fixed point: RMDs are mandatory
                # regardless of spending need, and their tax consequences
                # must feed back into the required withdrawal.
                trial_wd = withdrawal_engine.execute_withdrawals(
                    trial_needed, trial_balances, year, primary_age,
                    spouse_age, sale_date=date(year, 12, 31),
                    owner_map=owner_map, access_date=date(year, 1, 1),
                )
                # Undo trial basis mutation
                cost_basis.basis_by_account.clear()
                cost_basis.basis_by_account.update(basis_snapshot)
                withdrawal_engine.access.restore(access_snapshot)

                # ACA subsidy on trial withdrawal-inclusive MAGI.  The
                # subsidy can only offset the healthcare premium (the
                # ACA-eligible medical spend), not every expense — a
                # household's out-of-pocket is never reduced below
                # expenses minus the premium it actually replaces.
                if aca_family_size > 0:
                    aca_subsidy = monetary_policy.from_nominal_after_tax(tax_law_aca(
                        monetary_policy.to_nominal_for_tax(trial_magi, year),
                        aca_family_size, law, self.scenario.state), year)
                premium_base = min(annual_expenses, sum(max(0.0, actual_by_expense.get(e.id, 0.0) - funded_by_expense.get(e.id, 0.0)) for e in self.scenario.expenses if e.category == "medical" and not e.is_one_time))
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
                    other_income = (non_ss_income * inflate + _roth_conversion_income + withdrawal_ordinary
                                    + withdrawal_cg)
                else:
                    other_income = (non_ss_income + _roth_conversion_income
                                    + withdrawal_ordinary + withdrawal_cg)
                loss_limit = (1500 if filing_status == FilingStatus.MFS else 3000) / nominal_factor
                allowed_capital_net = max(-loss_limit, withdrawal_cg + event_capital_gains)
                other_income += investment_ordinary + investment_qualified + event_ordinary - pretax_deduction - hsa_deduction
                other_income += allowed_capital_net - withdrawal_cg
                taxable_ss = monetary_policy.from_nominal_after_tax(self.calculate_ss_taxable(
                    monetary_policy.to_nominal_for_tax(ss_income, year),
                    monetary_policy.to_nominal_for_tax(other_income, year)), year)

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
                    ordinary = (non_ss_income * inflate + _roth_conversion_income
                                + withdrawal_ordinary + taxable_ss)
                    capital_gains = withdrawal_cg
                else:
                    ordinary = (non_ss_income + _roth_conversion_income
                                + withdrawal_ordinary + taxable_ss)
                    capital_gains = withdrawal_cg

                # Convert to nominal for tax calculation (tax brackets are
                # always nominal; REAL-mode values convert, then back).
                ordinary += event_ordinary + investment_ordinary
                capital_gains += event_capital_gains
                ordinary -= pretax_deduction + hsa_deduction + expense_data.get("rental_interest", 0.0)
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
                    qualified_dividends=monetary_policy.to_nominal_for_tax(investment_qualified, year),
                    investment_ordinary=monetary_policy.to_nominal_for_tax(investment_ordinary, year),
                    tax_free=tax_free_nominal,
                    total=(tax_ordinary_nominal + tax_cg_nominal
                           + tax_free_nominal + monetary_policy.to_nominal_for_tax(investment_qualified, year)),
                )
                # Child Tax Credit: dependents under 17
                num_children = sum(
                    1 for dep in self.scenario.dependents
                    if 0 <= year - dep.birth_date.year < 17)
                taxes_nominal = self.calculate_taxes(
                    year, taxable_income_for_tax, scenario_name,
                    filing_status=filing_status,
                    inflation_rate=inflation_rate,
                    years_from_base=years_from_base,
                    num_children=num_children,
                    wages_by_owner=wages_for_tax,
                    **{**tax_options, "ca_income_adjustment": tax_options.get("ca_income_adjustment", 0.0) + monetary_policy.to_nominal_for_tax(hsa_deduction - taxable_ss, year)})
                # Convert tax back to the active convention (NIIT is already
                # included in calculate_taxes() via tax_law)
                taxes = monetary_policy.from_nominal_after_tax(
                    taxes_nominal, year, inflation_rate,
                )

                # Withdrawal-inclusive MAGI for the next ACA pass
                trial_magi = (annual_income - investment_cash + investment_ordinary + investment_qualified + withdrawal_ordinary
                              + allowed_capital_net + _roth_conversion_income + event_ordinary - pretax_deduction - hsa_deduction)

                new_needed = max(0.0, expenses_after_subsidy + taxes
                                 - annual_income)
                if abs(new_needed - trial_needed) <= max(0.05, abs(trial_needed) * 1e-6) and abs(taxes - old_tax) <= 0.05:
                    converged = True
                    break
                trial_needed = new_needed

            if not converged:
                # Safety net (marginal rates < 100% make this rare):
                # damped average of the last two iterates.
                trial_needed = (trial_needed + new_needed) / 2.0

            # Diagnose restrictions against remaining economic capital, before
            # executing the final draw. Shared Roth principal is consumed once.
            capacity_basis = dict(cost_basis.basis_by_account)
            capacity_access = withdrawal_engine.access.snapshot()
            economic_capacity = sum(max(0.0, balances.get(aid, 0.0)) for aid, a in run_accounts.items()
                if a.liquid and a.account_type not in {"real_estate", "vehicle", "529"})
            capacity_draws = withdrawal_engine.execute_withdrawals(
                economic_capacity, dict(balances), year, primary_age, spouse_age,
                sale_date=date(year, 12, 31), owner_map=owner_map, access_date=date(year, 1, 1))
            accessible_capacity = sum(w.amount for w in capacity_draws if w.tax_treatment != "rmd_reinvested")
            cost_basis.basis_by_account.clear()
            cost_basis.basis_by_account.update(capacity_basis)
            withdrawal_engine.access.restore(capacity_access)
            restricted_capacity = max(0.0, economic_capacity - accessible_capacity)

            # Execute exactly once on real balances at the converged amount
            needed = trial_needed
            if needed >= 0:
                withdrawals = withdrawal_engine.execute_withdrawals(
                    needed, balances, year, primary_age, spouse_age,
                    sale_date=date(year, 12, 31),
                    owner_map=owner_map, access_date=date(year, 1, 1),
                )
            else:
                withdrawals = []

            # If withdrawals could not fully cover the required amount
            # (illiquid assets remain, e.g. real estate), the household is
            # out of savings even though net worth may still be positive.
            covered = sum(w.amount if w.tax_treatment != "rmd_reinvested" else -w.amount for w in withdrawals)
            if (covered < needed - 1.0
                    and out_of_savings_year is None):
                out_of_savings_year = year

            unfunded = max(0.0, needed - covered)
            access_shortfall = min(unfunded, restricted_capacity)
            depletion_shortfall = max(0.0, unfunded - restricted_capacity)
            if access_shortfall > outcome_tolerance and access_shortfall_year is None:
                access_shortfall_year = year
            if (depletion_shortfall > outcome_tolerance or housing_shortfall > outcome_tolerance) and portfolio_depletion_year is None:
                portfolio_depletion_year = year

            annual_outcomes = outcome_tracker.observe(
                year, unfunded, access_shortfall, depletion_shortfall,
                housing_shortfall, spending_cut, outcome_tolerance)

            total_taxes += taxes
            total_aca_subsidy += subsidy_used
            total_aca_subsidy_estimate += aca_subsidy

            # Record this year's MAGI for future IRMAA lookback
            # (MAGI is always nominal for IRS purposes)
            magi = tax_ordinary_nominal + max(-1500 if filing_status == FilingStatus.MFS else -3000, tax_cg_nominal) + monetary_policy.to_nominal_for_tax(investment_qualified, year)
            magi_history[year] = magi

            # --- Step 7c: Allocate surplus savings into accounts ---
            # Savings = income - expenses - taxes.  Distribute by account
            # contribution priority (401k → HSA → Roth → brokerage …).
            # Only while at least one person is still working.
            contribs = {}
            available_savings = max(0.0, annual_income - expenses_after_subsidy - taxes)
            if available_savings > 0:
                if active_owners:
                    contribs = withdrawal_engine.contribute(balances, available_savings, year, active_owners, ages, wages_active, cap_factor)
                    total_contributions += sum(contribs.values())
                employee_spent = sum(employee_amount(aid, total) for aid, total in contribs.items())
                leftover = max(0.0, available_savings - employee_spent)
                if leftover:
                    balances[surplus_destination] += leftover
                    cost_basis.set_basis(surplus_destination, cost_basis.get_basis(surplus_destination, 0.0) + leftover)

            # --- Step 9: Track net worth ---
            total_assets = sum(b for b in balances.values() if b > 0)
            total_liabs = sum(abs(b) for b in balances.values() if b < 0)
            total_liabs += sum(
                b / nominal_factor for b in mortgage_balances.values() if b > 0)
            net_worth = total_assets - total_liabs
            # Track per-age net worth for every run, not just stochastic.
            # The Monte Carlo simulator aggregates this into per-year
            # percentile bands for the fan chart, and the stochastic
            # mortality path also uses it for the age-indexed distribution.
            net_worth_by_year[primary_age] = net_worth

            # --- Estate tax (second death only, R8) ---
            # Assessed once at the second configured death year. The
            # first-death spousal transfer does not trigger estate tax.
            # Equal death years use the combined/MFJ estate convention;
            # otherwise the survivor's estate is single.
            year_estate_tax = 0.0
            if snap.estate_event and total_estate_tax == 0.0:
                estate_filing = (
                    FilingStatus.MFJ if snap.first_death_year is None
                    else FilingStatus.SINGLE)
                estate_nominal = monetary_policy.to_nominal_for_tax(
                    net_worth, year, inflation_rate)
                estate_tax_nominal = tax_law_estate(
                    estate_nominal, law, estate_filing)
                year_estate_tax = monetary_policy.from_nominal_after_tax(
                    estate_tax_nominal, year, inflation_rate)
                total_estate_tax = year_estate_tax

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
                    "primary_age": primary_age,
                    "spouse_age": spouse_age,
                    "income": annual_income,
                    "income_by_source": {**{k: monetary_policy.adjust_for_inflation(v, year) for k, v in income_data["by_source"].items()}, **({"Social Security": ss_income} if ss_income > 0 else {}), **({"Cash investment distributions": investment_cash} if investment_cash > 0 else {})},
                    "expenses_by_category": expense_data["by_category"],
                    "expenses_by_id": dict(actual_by_expense),
                    "planned_expenses": planned_spending,
                    **annual_outcomes,
                    "spending_cut": spending_cut,
                    "spending_cut_fraction": spending_cut / planned_spending if planned_spending else 0.0,
                    "investment_income": investment_ordinary + investment_qualified + investment_capital_gains,
                    "investment_cash_income": investment_cash,
                    "investment_income_by_account": investment_by_account,
                    "qualified_dividends_nominal": monetary_policy.to_nominal_for_tax(investment_qualified, year),
                    "capital_gain_distributions_nominal": monetary_policy.to_nominal_for_tax(investment_capital_gains, year),
                    "magi_nominal": magi,
                    "input_readiness": self.input_readiness,
                    "net_cash_flow": annual_income - annual_expenses - taxes + subsidy_used,
                    "account_balances": dict(balances),
                    "taxable_cash_opening": taxable_cash_opening,
                    "accessible_spending_balance": accessible_capacity if access_assessed else None,
                    "restricted_spending_balance": restricted_capacity if access_assessed else None,
                    "access_shortfall": access_shortfall if access_assessed else None,
                    "portfolio_depletion_shortfall": depletion_shortfall,
                    "withdrawals_by_account": {aid: sum(w.amount for w in withdrawals if w.account_id == aid and w.tax_treatment != "rmd_reinvested") for aid in balances},
                    "roth_conversion_schedule": withdrawal_engine.access.schedule(),
                    "taxable_basis_nominal": {aid: value * nominal_factor for aid, value in cost_basis.basis_by_account.items()},
                    "mortgage_balances_nominal": dict(mortgage_balances),
                    "contributions": dict(contribs) if not primary_retired or not spouse_retired else {},
                    "withdrawals": sum(w.amount for w in withdrawals if w.tax_treatment != "rmd_reinvested"),
                    "estate_value_before_tax": net_worth if snap.estate_event else None,
                    "net_worth_after_estate": net_worth - year_estate_tax if snap.estate_event else None,
                    "approximations": [],
                    "model_warnings": list(self.model_warnings),
                    "expenses": annual_expenses + funded_expenses,
                    "cash_expenses": annual_expenses,
                    "funded_expenses": funded_expenses,
                    "taxes": taxes,
                    "ordinary_income_nominal": tax_ordinary_nominal,
                    "capital_gains_nominal": tax_cg_nominal,
                    "aca_subsidy": subsidy_used,
                    "aca_subsidy_estimate": aca_subsidy,
                    "net_worth": net_worth,
                    "total_assets": total_assets,
                    "total_liabilities": total_liabs,
                    # Survivor transition state (additive, KTD9)
                    "primary_alive": snap.primary_alive,
                    "spouse_alive": snap.spouse_alive,
                    "filing_status": snap.filing_status.value,
                    "survivor": snap.survivor,
                    "estate_tax": year_estate_tax,
                    "aca_family_size": snap.aca_family_size,
                    "medicare_adult_count": snap.medicare_adult_count,
                    "expense_ratio": survivor_expense_ratio,
                })

            if net_worth > peak_nw:
                peak_nw = net_worth

            # Update portfolio peak for guardrails/withdrawal strategies
            total_portfolio = self._liquid_portfolio(balances)
            if total_portfolio > portfolio_peak:
                portfolio_peak = total_portfolio

            if net_worth <= 0 and out_of_savings_year is None:
                out_of_savings_year = year

        final_nw = (sum(balances.values())
                    - sum(b / nominal_factor for b in mortgage_balances.values() if b > 0))
        # Net of estate tax for success calculation
        final_nw_after_estate = final_nw - total_estate_tax
        success = (final_nw_after_estate > monetary_policy.adjust_for_inflation(self.scenario.legacy_goal, year)
                   and out_of_savings_year is None)

        # Single-household and stochastic paths do not emit the two-person
        # estate event. Estimate terminal estate tax for the separate legacy
        # goal, without changing historical cash-flow or success fields.
        legacy_estate_tax = total_estate_tax
        estate_tax_timing = "annual_projection"
        if not snap.estate_event:
            estate_filing = FilingStatus.MFJ if self.scenario.spouse is not None and snap.first_death_year is None else FilingStatus.SINGLE
            legacy_estate_tax = monetary_policy.from_nominal_after_tax(
                tax_law_estate(monetary_policy.to_nominal_for_tax(final_nw, year), law, estate_filing), year)
            estate_tax_timing = "terminal_estimate"
        goal_outcomes = outcome_tracker.finish(
            final_nw - legacy_estate_tax,
            monetary_policy.adjust_for_inflation(self.scenario.legacy_goal, year))
        goal_outcomes.update({"base_year": self.start_year, "final_year": year,
                              "monetary_convention": self.scenario.monetary_convention.value,
                              "legacy_target_base_year": self.scenario.legacy_goal,
                              "final_wealth_after_estate": final_nw - legacy_estate_tax,
                              "estate_tax": legacy_estate_tax,
                              "estate_tax_timing": estate_tax_timing})
        return {
            "success": success,
            "outcomes": goal_outcomes,
            "model_warnings": list(self.model_warnings),
            "input_readiness": self.input_readiness,
            "years_with_spending_cuts": years_with_spending_cuts,
            "maximum_spending_cut_fraction": maximum_spending_cut_fraction,
            "final_net_worth": final_nw,
            "estate_value_before_tax": final_nw,
            "net_worth_after_estate": final_nw_after_estate,
            "final_net_worth_after_estate_tax": final_nw_after_estate,
            "estate_tax": total_estate_tax,
            "aca_subsidy": total_aca_subsidy,
            "aca_subsidy_estimate": total_aca_subsidy_estimate,
            "peak_net_worth": peak_nw,
            "lifetime_taxes": total_taxes,
            "lifetime_ss": total_ss,
            "lifetime_contributions": total_contributions,
            "out_of_savings_year": out_of_savings_year,
            "access_shortfall_year": access_shortfall_year if access_assessed else None,
            "portfolio_depletion_year": portfolio_depletion_year,
            "withdrawal_access_policy": self.scenario.withdrawal_access_policy,
            "death_age": stochastic_death_age,
            "net_worth_by_year": net_worth_by_year,
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
    def project_cash_flow(self, scenario_name: str = "mean",
                          stress_level: Optional[float] = None) -> List[Dict]:
        """Generate year-by-year cash flow projection (deterministic).

        *stress_level* (0..1) cuts discretionary expenses by
        min_reduction × stress_level — same semantics as the MC path.
        """
        from .approximations import ApproximationTracker, AGGREGATE_BASIS_WARNING, DETERMINISTIC_RETURNS_WARNING
        tracker = ApproximationTracker()
        tracker.add(DETERMINISTIC_RETURNS_WARNING)
        if any(a.tax_treatment == "taxable" for a in self.accounts.values()):
            tracker.add(AGGREGATE_BASIS_WARNING)
        rows = self.run_single_simulation(scenario_name, return_volatility=0.0, collect_projections=True, stress_level=stress_level)["projections"]
        for row in rows:
            row["approximations"] = [a.as_dict() for a in tracker.for_year(row["year"])]
        return rows
