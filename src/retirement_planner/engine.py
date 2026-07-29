"""
Core retirement planning engine.

Key design decisions (all monetary values are in REAL dollars unless noted):
- Investment returns are REAL (inflation-adjusted), so expenses stay flat
  in real terms — no inflation multiplier applied to expenses.
- Withdrawals follow a tax-efficient order: RMD → taxable → pre-tax → Roth.
- Taxes distinguish ordinary income, long-term capital gains, and tax-free.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime, date
import math
import numpy as np
from dataclasses import dataclass, field
from enum import Enum

from .models import (
    Scenario, Person, Account, IncomeStream, Expense,
    Mortgage, Windfall, HousingEvent, RothConversion,
    EconomicAssumptions, SocialSecurity, AgeEvent, TaxableIncome,
    AssetAllocation, GlidepathConfig,
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
    """Tracks cost basis per account for capital gains calculations."""
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
    ) -> List[WithdrawalResult]:
        """Withdraw from accounts in tax-efficient order until *needed* is met.

        Returns a list of ``WithdrawalResult`` objects.  Side-effects
        update *balances* and ``cost_basis`` in place.
        """
        self.clear()
        remaining = needed
        older_age = max(primary_age, spouse_age)

        # --- Step 1: Force RMDs from pre-tax accounts (age 73+) ---
        if older_age >= RMD_START_AGE:
            remaining = self._withdraw_rmds(balances, older_age, remaining)

        # --- Step 2: Taxable brokerage ---
        remaining = self._withdraw_from_category(
            balances, remaining,
            category_filter=lambda a: a.tax_treatment == "taxable",
            tax_treatment="capital_gains",
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
        age: int,
        remaining: float,
    ) -> float:
        """Force RMDs from all pre-tax accounts, return remaining shortfall."""
        for account_id, account in self.accounts.items():
            if account.tax_treatment != "pre_tax":
                continue
            balance = balances.get(account_id, 0.0)
            if balance <= 0:
                continue
            rmd = self.calculate_rmd(balance, age)
            if rmd <= 0:
                continue
            # RMD can't exceed account balance
            actual = min(rmd, balance)
            gain = actual - self.cost_basis.debit_basis(account_id, actual)
            balances[account_id] = balance - actual
            self._withdrawals.append(WithdrawalResult(
                account_id=account_id,
                account_type=account.account_type,
                amount=actual,
                tax_treatment="ordinary",
                taxable_amount=actual,  # Entire pre-tax withdrawal is ordinary income
                capital_gain=max(0.0, gain),
            ))
            remaining = max(0.0, remaining - actual)
        return remaining

    def _withdraw_from_category(
        self,
        balances: Dict[str, float],
        remaining: float,
        category_filter,
        tax_treatment: str,
    ) -> float:
        """Withdraw from accounts matching *category_filter* until remaining is 0."""
        for account_id, account in self.accounts.items():
            if remaining <= 0:
                break
            if not category_filter(account):
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
                capital_gain = max(0.0, withdraw - basis_used)
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
# Tax calculation with income-type awareness
# ---------------------------------------------------------------------------
def _indexed_brackets(brackets, factor):
    """Return a new bracket list with limits scaled by *factor*."""
    if factor == 1.0:
        return brackets
    return [(limit * factor, rate) for limit, rate in brackets]


def _bracket_tax(taxable_income: float, brackets: List[Tuple[float, float]]) -> float:
    """Compute tax from a list of (upper_limit, rate) brackets."""
    tax = 0.0
    prev_limit = 0.0
    for limit, rate in brackets:
        if taxable_income <= prev_limit:
            break
        taxable_in_bracket = min(taxable_income, limit) - prev_limit
        tax += taxable_in_bracket * rate
        prev_limit = limit
    return tax


# 2024 MFJ ordinary income brackets
_FEDERAL_BRACKETS: List[Tuple[float, float]] = [
    (23_200, 0.10),
    (94_300, 0.12),
    (201_050, 0.22),
    (383_900, 0.24),
    (487_450, 0.32),
    (731_200, 0.35),
    (float('inf'), 0.37),
]

# 2024 long-term capital gains brackets (MFJ)
_LTCG_BRACKETS: List[Tuple[float, float]] = [
    (94_050, 0.00),
    (583_750, 0.15),
    (float('inf'), 0.20),
]

# California 2024 MFJ brackets
_CA_BRACKETS: List[Tuple[float, float]] = [
    (20_824, 0.01),
    (49_368, 0.02),
    (77_918, 0.04),
    (108_152, 0.06),
    (136_700, 0.08),
    (698_274, 0.093),
    (837_922, 0.103),
    (1_396_546, 0.113),
    (1_666_074, 0.123),
    (2_732_666, 0.133),
    (float('inf'), 0.143),
]


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
        try:
            with open(config_path) as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(
                f"Invalid JSON in config file '{config_path}': {e.msg}",
                e.doc, e.pos)
        
        # Parse config into Scenario
        # This is a simplified parser - full implementation would handle all fields
        from datetime import date
        
        primary = Person(
            name=config["primary"]["name"],
            birth_date=date.fromisoformat(config["primary"]["birth_date"]),
            retirement_date=date.fromisoformat(config["primary"]["retirement_date"]),
            longevity_age=config["primary"].get("longevity_age", 90),
        )
        
        spouse = Person(
            name=config["spouse"]["name"],
            birth_date=date.fromisoformat(config["spouse"]["birth_date"]),
            retirement_date=date.fromisoformat(config["spouse"]["retirement_date"]),
            longevity_age=config["spouse"].get("longevity_age", 90),
        )
        
        # Parse accounts
        accounts = []
        for acc_config in config.get("accounts", []):
            accounts.append(Account(
                id=acc_config["id"],
                name=acc_config["name"],
                account_type=acc_config["type"],
                tax_treatment=acc_config.get("tax_treatment", "taxable"),
                balance=acc_config["balance"],
                growth_rate=acc_config.get("growth_rate", 0.088),
                monthly_contribution=acc_config.get("monthly_contribution", 0.0),
                employer_match=acc_config.get("employer_match", 0.0),
                employer_match_limit=acc_config.get("employer_match_limit", 0.0),
                contribution_priority=acc_config.get("contribution_priority", 0),
                annual_contribution_cap=acc_config.get("annual_contribution_cap", 0.0),
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
                    end_date=date.fromisoformat(ec["end_date"]) if ec.get("end_date") else None,
                    sell_to_cover=ec.get("sell_to_cover", True),
                    is_taxable=ec.get("is_taxable", True),
                    goes_to_account=ec.get("goes_to_account", ""),
                )

            # Compute monthly_amount from base_salary if provided (legacy compat)
            monthly_amount = ic.get("monthly_amount", 0)
            if base_salary and monthly_amount == 0:
                monthly_amount = base_salary["annual"] / 12

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
            one_time_date = ec.get("one_time_date")
            expenses.append(Expense(
                id=ec["id"],
                name=ec["name"],
                monthly_amount=ec["monthly_amount"],
                start_date=date.fromisoformat(ec["start_date"]),
                end_date=date.fromisoformat(ec["end_date"]),
                growth_rate=ec.get("growth_rate", 0.0),
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
        social_security = SocialSecurity(
            primary_benefit_at_67=ss_config.get("primary_benefit_at_67", 3000),
            primary_claiming_age=ss_config.get("primary_claiming_age", 67),
            spouse_benefit_at_67=ss_config.get("spouse_benefit_at_67", 2500),
            spouse_claiming_age=ss_config.get("spouse_claiming_age", 67),
            cola_rate=ss_config.get("cola_rate", 0.0254),
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
            age_events=age_events,
            social_security=social_security,
            legacy_goal=config.get("legacy_goal", 2_000_000),
            state=config.get("state", "CA"),
            savings_order=savings_order,
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

        Bond rate: general_inflation + 0.01 (real bond return ≈ 1%
        above inflation).
        Equity rate: account.growth_rate (the real equity return).
        """
        rates = self.scenario.economic.get_rate("mean")
        inflation = rates["general_inflation"]

        bond_rate = inflation + 0.01  # Real bond return
        equity_rate = account.growth_rate  # Real equity return

        gross_rate = (equity_rate * allocation.equity_pct
                      + bond_rate * allocation.bond_pct)
        net_rate = gross_rate - account.expense_ratio
        return net_rate

    def get_account_balance(self, account_id: str, year: int,
                            scenario: str = "mean") -> float:
        """Get projected account balance for a given year (deterministic)."""
        account = self.accounts.get(account_id)
        if not account:
            return 0.0

        years = year - self.start_year
        rates = self.scenario.economic.get_rate(scenario)

        if account.account_type == "real_estate":
            rate = rates["housing_appreciation"]
        elif account.is_depreciating:
            rate = -0.04
        elif account.growth_rate == 0:
            rate = 0
        else:
            rate = account.growth_rate

        return account.project_balance(years, rate)

    def calculate_net_worth(self, year: int, scenario: str = "mean") -> Dict:
        """Calculate net worth at a given year."""
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

        return {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "net_worth": total_assets - total_liabilities,
            "accounts": account_balances,
        }

    # ------------------------------------------------------------------
    # Income
    # ------------------------------------------------------------------
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
            if stream.start_date.year <= year <= stream.end_date.year:
                years_active = year - stream.start_date.year

                if stream.base_salary or stream.equity:
                    # Enhanced mode: base + bonus + equity
                    stream_income = 0

                    # Base salary
                    if stream.base_salary:
                        base = stream.base_salary["annual"]
                        growth = stream.base_salary.get("growth_rate", 0)
                        stream_income += base * (1 + growth) ** years_active

                    # Bonus (annual lump sum)
                    if stream.bonus and stream.bonus.annual > 0:
                        bonus_growth = stream.bonus.growth_rate
                        stream_income += stream.bonus.annual * (1 + bonus_growth) ** years_active

                    # RSU equity
                    if stream.equity and stream.equity.ticker:
                        rsu_income = self.calculate_annual_rsu_income(year, stream.equity)
                        stream_income += rsu_income
                        if rsu_income > 0:
                            income_by_source[f"{stream.name} — RSU"] = rsu_income

                    total_income += stream_income
                    if stream.base_salary:
                        income_by_source[stream.name] = stream_income
                else:
                    # Legacy mode: flat monthly amount with growth
                    amount = (stream.monthly_amount * 12
                              * (1 + stream.growth_rate) ** years_active)
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

                    # Apply stress reduction for discretionary expenses
                    if stress_level > 0 and not expense.is_must_spend:
                        reduction = expense.min_reduction * stress_level
                        amount *= (1.0 - reduction)

                    total_expenses += amount
                    expenses_by_category[expense.name] = amount

        # Add mortgage payments (amortized when balances are tracked)
        for mortgage in self.scenario.mortgages:
            if mortgage.start_date.year <= year <= mortgage.end_date.year:
                if mortgage_balances is not None:
                    balance = mortgage_balances.get(mortgage.id, 0.0)
                    if balance <= 0:
                        continue  # Paid off — no more payments
                    interest = balance * mortgage.interest_rate
                    annual_payment = mortgage.monthly_payment * 12
                    # Final payoff year may need less than a full payment
                    amount = min(annual_payment, balance + interest)
                    principal = amount - interest
                    mortgage_balances[mortgage.id] = max(
                        0.0, balance - principal)
                else:
                    amount = mortgage.monthly_payment * 12
                total_expenses += amount
                expenses_by_category[f"Mortgage - {mortgage.name}"] = amount

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
        idx = (1.0 + inflation_rate) ** years_from_base
        if filing_status == "MFJ":
            exemption = _ESTATE_EXEMPTION_MFJ * idx
        else:
            exemption = _ESTATE_EXEMPTION_SINGLE * idx

        if net_worth <= exemption:
            return 0.0

        excess = net_worth - exemption
        return excess * _ESTATE_TAX_RATE

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
            base_spending: The baseline annual spending (year 1 expenses).
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
                if exp.start_date.year <= year <= exp.end_date.year:
                    must_spend_total += exp.monthly_amount * 12
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

        Reads ``self.scenario.withdrawal_strategy`` and delegates to
        the appropriate method.  Returns base_spending unchanged for
        the 'fixed' strategy (backward compatible).

        Args:
            year: Current calendar year.
            base_spending: Base annual expenses from calculate_annual_expenses().
            portfolio_value: Current total portfolio value.
            portfolio_peak: High-water mark of portfolio value.
            expenses: Dict with 'total' and 'by_category' from expenses calculation.

        Returns:
            Adjusted annual spending amount.
        """
        strategy = getattr(self.scenario, 'withdrawal_strategy', 'fixed')

        if strategy == 'fixed':
            return base_spending

        elif strategy == 'guardrails':
            return self.apply_guardrails(
                year, base_spending, portfolio_value, portfolio_peak,
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
                    if exp.start_date.year <= year <= exp.end_date.year:
                        floor += exp.monthly_amount * 12
            withdrawal_rate = getattr(self.scenario, 'withdrawal_rate', 0.04)
            return self.apply_percent_of_portfolio(
                year, portfolio_value, withdrawal_rate, floor,
            )

        elif strategy == 'floor_ceiling':
            # Compute floor (must-spend) and ceiling (base + 20%)
            floor = 0.0
            for exp in self.scenario.expenses:
                if exp.is_must_spend and not exp.is_one_time:
                    if exp.start_date.year <= year <= exp.end_date.year:
                        floor += exp.monthly_amount * 12
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
        """
        total_taxes = 0.0
        total_ss = 0.0
        total_contributions = 0.0
        total_aca_subsidy = 0.0
        total_estate_tax = 0.0
        peak_nw = 0.0
        out_of_savings_year = None

        # Starting balances
        balances: Dict[str, float] = {}
        for account_id, account in self.accounts.items():
            balances[account_id] = account.balance

        # Track mortgage balances separately — amortized annually and
        # subtracted from net worth as liabilities.
        mortgage_balances: Dict[str, float] = {}
        for mortgage in self.scenario.mortgages:
            mortgage_balances[mortgage.id] = mortgage.balance

        # Initialize cost basis — for simplicity, assume initial basis
        # equals current balance (all contributions up to now).
        # A real implementation would track actual contributions.
        cost_basis = CostBasisTracker()
        for account_id, account in self.accounts.items():
            if account.tax_treatment == "taxable":
                cost_basis.set_basis(account_id, account.balance)

        rates = self.scenario.economic.get_rate(scenario_name)
        inflation_rate = rates["general_inflation"]
        withdrawal_engine = WithdrawalEngine(self.accounts, cost_basis)

        # Track MAGI by year for IRMAA 2-year lookback
        magi_history: Dict[int, float] = {}

        # Withdrawal strategy tracking
        portfolio_peak = 0.0
        base_spending = None  # Will be set on first retirement year

        # Historical return sequence index (for sequential replay)
        _hist_idx = 0

        max_year = (self.scenario.primary.birth_date.year
                    + self.scenario.primary.longevity_age + 1)

        for year in range(self.start_year, max_year):
            primary_age = year - self.scenario.primary.birth_date.year
            spouse_age = year - self.scenario.spouse.birth_date.year
            younger_age = min(primary_age, spouse_age)
            years_from_base = year - self.start_year

            if (primary_age > self.scenario.primary.longevity_age
                    and spouse_age > self.scenario.spouse.longevity_age):
                break

            # --- Step 1: Investment returns (with optional volatility) ---
            for account_id in list(balances.keys()):
                balance = balances[account_id]
                if balance <= 0:
                    continue
                account = self.accounts[account_id]

                if account.account_type == "real_estate":
                    base_rate = rates["housing_appreciation"]
                elif account.is_depreciating:
                    base_rate = -0.04
                elif account.growth_rate == 0:
                    base_rate = 0
                else:
                    # Use equity glidepath if configured
                    allocation = self.get_equity_allocation(primary_age)
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
                    # Use pre-computed historical return sequence
                    actual_rate = self._historical_return_override[_hist_idx]
                elif return_volatility > 0:
                    actual_rate = np.random.normal(base_rate, return_volatility)
                else:
                    actual_rate = base_rate

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

            # Social Security
            ss_income = 0.0
            if primary_age >= self.scenario.social_security.primary_claiming_age:
                ss_income += self.calculate_social_security(
                    year, self.scenario.primary)
            if spouse_age >= self.scenario.social_security.spouse_claiming_age:
                ss_income += self.calculate_social_security(
                    year, self.scenario.spouse)
            annual_income += ss_income
            total_ss += ss_income

            # --- Step 4: Expenses ---
            expense_data = self.calculate_annual_expenses(
                year, scenario_name, mortgage_balances=mortgage_balances)
            annual_expenses = expense_data["total"]

            # --- Step 4b: IRMAA Medicare surcharges (age >= 65) ---
            older_age = max(primary_age, spouse_age)
            irmaa_amount = 0.0
            if older_age >= 65:
                # 2-year lookback: use MAGI from 2 years prior
                lookback_year = year - 2
                magi_2yr_ago = magi_history.get(lookback_year, 0.0)
                irmaa_amount = self.calculate_irmaa(magi_2yr_ago, older_age)
                annual_expenses += irmaa_amount

            # --- Step 4c: ACA subsidy (pre-Medicare, age < 65) ---
            if younger_age < 65:
                aca_subsidy = self.calculate_aca_subsidy(
                    annual_income, self.scenario.family_size, self.scenario.state)
                annual_expenses = max(0.0, annual_expenses - aca_subsidy)
                total_aca_subsidy += aca_subsidy

            # --- Step 4d: Apply withdrawal strategy (if retired) ---
            total_portfolio_value = sum(b for b in balances.values() if b > 0)

            if primary_retired and spouse_retired:
                # Set base spending from first retirement year
                if base_spending is None:
                    base_spending = annual_expenses

                # Apply withdrawal strategy to adjust spending
                annual_expenses = self.apply_withdrawal_strategy(
                    year, base_spending, total_portfolio_value,
                    portfolio_peak, expense_data,
                )

            # --- Step 5: Withdrawals (tax-efficient order) ---
            shortfall = withdrawal_engine.calculate_withdrawal_needed(
                year, annual_expenses, annual_income, ss_income,
            )

            withdrawals = []
            if shortfall > 0:
                withdrawals = withdrawal_engine.execute_withdrawals(
                    shortfall, balances, year, primary_age, spouse_age,
                )

            # --- Step 6: Build TaxableIncome from all sources ---
            # Calculate SS taxable portion (uses income BEFORE SS was added)
            non_ss_income = income_data["total"]  # wages + other non-SS income
            taxable_ss = self.calculate_ss_taxable(ss_income, non_ss_income)

            # Ordinary income = non-SS wages/withdrawals + taxable SS portion
            ordinary = non_ss_income
            capital_gains = 0.0
            tax_free = 0.0
            for w in withdrawals:
                if w.tax_treatment == "ordinary":
                    ordinary += w.taxable_amount
                elif w.tax_treatment == "capital_gains":
                    capital_gains += w.capital_gain
                elif w.tax_treatment == "tax_free":
                    tax_free += w.amount
            ordinary += taxable_ss  # Only the taxable portion of SS

            total = ordinary + capital_gains + tax_free
            taxable_income = TaxableIncome(
                ordinary=ordinary,
                capital_gains=capital_gains,
                tax_free=tax_free,
                total=total,
            )

            # --- Step 7: Taxes ---
            taxes = self.calculate_taxes(
                year, taxable_income, scenario_name,
                inflation_rate=inflation_rate,
                years_from_base=years_from_base)

            # --- Step 7b: NIIT (Net Investment Income Tax) ---
            investment_income = capital_gains
            magi = ordinary + capital_gains  # MAGI approximation
            niit = self.calculate_niit(investment_income, magi)
            taxes += niit

            total_taxes += taxes

            # Record this year's MAGI for future IRMAA lookback
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
                    if target and target in balances:
                        balances[target] += windfall.amount
                        # Increase basis for taxable windfalls
                        acct = self.accounts.get(target)
                        if acct and acct.tax_treatment == "taxable":
                            current_basis = cost_basis.get_basis(target, 0.0)
                            cost_basis.set_basis(target, current_basis + windfall.amount)

            # --- Step 9: Track net worth ---
            total_assets = sum(b for b in balances.values() if b > 0)
            total_liabs = sum(abs(b) for b in balances.values() if b < 0)
            total_liabs += sum(
                b for b in mortgage_balances.values() if b > 0)
            net_worth = total_assets - total_liabs

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
                total_estate_tax = self.calculate_estate_tax(
                    net_worth, "MFJ", inflation_rate, years_from_base)

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
        projections = []
        cost_basis = CostBasisTracker()
        for account_id, account in self.accounts.items():
            if account.tax_treatment == "taxable":
                cost_basis.set_basis(account_id, account.balance)

        rates = self.scenario.economic.get_rate(scenario_name)
        inflation_rate = rates["general_inflation"]
        total_estate_tax = 0.0

        max_year = (self.scenario.primary.birth_date.year
                    + self.scenario.primary.longevity_age + 1)

        for year in range(self.start_year, max_year):
            primary_age = year - self.scenario.primary.birth_date.year
            spouse_age = year - self.scenario.spouse.birth_date.year
            younger_age = min(primary_age, spouse_age)
            years_from_base = year - self.start_year

            if (primary_age > self.scenario.primary.longevity_age
                    and spouse_age > self.scenario.spouse.longevity_age):
                break

            income = self.calculate_annual_income(year, scenario_name)
            expenses = self.calculate_annual_expenses(year, scenario_name)

            # ACA subsidy (pre-Medicare, age < 65)
            aca_subsidy = 0.0
            if younger_age < 65:
                aca_subsidy = self.calculate_aca_subsidy(
                    income["total"], self.scenario.family_size, self.scenario.state)

            # Build TaxableIncome (simplified — all income as ordinary
            # for deterministic projection; real sim handles this properly)
            ti = TaxableIncome(
                ordinary=income["total"],
                capital_gains=0.0,
                tax_free=0.0,
                total=income["total"],
            )
            taxes = self.calculate_taxes(
                year, ti, scenario_name,
                inflation_rate=inflation_rate,
                years_from_base=years_from_base)
            net_worth = self.calculate_net_worth(year, scenario_name)

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
            })

        return projections
