"""
Core retirement planning engine.

Key design decisions (all monetary values are in REAL dollars unless noted):
- Investment returns are REAL (inflation-adjusted), so expenses stay flat
  in real terms — no inflation multiplier applied to expenses.
- Withdrawals follow a tax-efficient order: RMD → taxable → pre-tax → Roth.
- Taxes distinguish ordinary income, long-term capital gains, and tax-free.
"""
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import math
import random
from dataclasses import dataclass, field
from enum import Enum

from .models import (
    Scenario, Person, Account, IncomeStream, Expense,
    Mortgage, Windfall, HousingEvent, RothConversion,
    EconomicAssumptions, SocialSecurity, AgeEvent, TaxableIncome,
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
        year: int,
    ) -> Dict[str, float]:
        """Add monthly contributions + employer match to each account.

        Returns dict of {account_id: total_contribution} for logging.
        """
        contributions: Dict[str, float] = {}
        for account_id, account in self.accounts.items():
            if account.monthly_contribution <= 0 and account.employer_match <= 0:
                continue

            employee = account.monthly_contribution * 12

            # Employer match: match up to match_limit of employee contribution
            match = 0.0
            if account.employer_match > 0 and account.employer_match_limit > 0:
                matchable = min(employee, account.employer_match_limit)
                match = matchable * account.employer_match
            elif account.employer_match > 0:
                match = employee * account.employer_match

            total = employee + match
            if total > 0:
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
    @classmethod
    def from_config(cls, config_path: str) -> 'RetirementPlanner':
        """Load planner from JSON config file."""
        import json
        with open(config_path) as f:
            config = json.load(f)
        
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
            ))
        
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
        income_streams = []
        for ic in config.get("income_streams", []):
            income_streams.append(IncomeStream(
                id=ic["id"],
                name=ic["name"],
                owner=ic["owner"],
                monthly_amount=ic["monthly_amount"],
                start_date=date.fromisoformat(ic["start_date"]),
                end_date=date.fromisoformat(ic["end_date"]),
                growth_rate=ic.get("growth_rate", 0.0),
                is_w2=ic.get("is_w2", True),
                is_passive=ic.get("is_passive", False),
                is_ss=ic.get("is_ss", False),
                goes_to_account=ic.get("goes_to_account", ""),
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
        )
        
        return cls(scenario)

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
        """Calculate total income for a year."""
        total_income = 0
        income_by_source = {}

        for stream in self.scenario.income_streams:
            if stream.start_date.year <= year <= stream.end_date.year:
                years_active = year - stream.start_date.year
                amount = (stream.monthly_amount * 12
                          * (1 + stream.growth_rate) ** years_active)
                total_income += amount
                income_by_source[stream.name] = amount

        return {"total": total_income, "by_source": income_by_source}

    # ------------------------------------------------------------------
    # Expenses  — FIX: no inflation multiplier (returns are real)
    # ------------------------------------------------------------------
    def calculate_annual_expenses(
        self,
        year: int,
        scenario: str = "mean",
        stress_level: float = 0.0,
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

        # Add mortgage payments
        for mortgage in self.scenario.mortgages:
            if mortgage.start_date.year <= year <= mortgage.end_date.year:
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
    # Taxes  — REWRITE: accepts TaxableIncome, distinguishes income types
    # ------------------------------------------------------------------
    def calculate_taxes(
        self,
        year: int,
        income: "TaxableIncome",
        scenario: str = "mean",
    ) -> float:
        """Calculate federal + CA state taxes using income-type breakdown.

        Args:
            year: Calendar year (reserved for future bracket inflation).
            income: TaxableIncome object with ordinary, capital_gains,
                    and tax_free fields populated.
            scenario: Economic scenario (reserved for future use).

        Returns:
            Total tax liability (federal + state).
        """
        # Standard deduction
        standard_deduction = 29_200

        # ---- Federal ordinary income tax ----
        # Apply standard deduction against ordinary income first
        ordinary_after_deduction = max(0.0, income.ordinary - standard_deduction)
        federal_ordinary = _bracket_tax(ordinary_after_deduction, _FEDERAL_BRACKETS)

        # ---- Federal long-term capital gains tax ----
        # LTCG stacks on top of ordinary income for bracket determination
        ltcg_taxable = income.capital_gains
        if ltcg_taxable > 0:
            # LTCG bracket thresholds are reduced by ordinary income
            remaining_ordinary = ordinary_after_deduction
            ltcg_tax = 0.0
            prev_threshold = 0.0
            for bracket_top, rate in _LTCG_BRACKETS:
                if ltcg_taxable <= 0:
                    break
                # How much of this LTCG bracket is available
                bracket_floor = max(prev_threshold - remaining_ordinary, 0.0)
                bracket_width = bracket_top - prev_threshold
                available = bracket_width - bracket_floor
                if available <= 0:
                    continue
                taxed_here = min(ltcg_taxable, available)
                ltcg_tax += taxed_here * rate
                ltcg_taxable -= taxed_here
                prev_threshold = bracket_top
        else:
            ltcg_tax = 0.0

        federal_tax = federal_ordinary + ltcg_tax

        # ---- California state tax (all ordinary — CA taxes LTCG as ordinary) ----
        ca_total = income.ordinary + income.capital_gains
        ca_taxable = max(0.0, ca_total - standard_deduction)
        ca_tax = _bracket_tax(ca_taxable, _CA_BRACKETS)

        return federal_tax + ca_tax

    # Legacy signature wrapper for backward compatibility
    def _calculate_taxes_legacy(self, year: int, income: float,
                                scenario: str = "mean") -> float:
        """Calculate taxes treating all income as ordinary (legacy)."""
        ti = TaxableIncome(ordinary=income, capital_gains=0.0,
                           tax_free=0.0, total=income)
        return self.calculate_taxes(year, ti, scenario)

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
        peak_nw = 0.0
        out_of_savings_year = None

        # Starting balances
        balances: Dict[str, float] = {}
        for account_id, account in self.accounts.items():
            balances[account_id] = account.balance

        # Initialize cost basis — for simplicity, assume initial basis
        # equals current balance (all contributions up to now).
        # A real implementation would track actual contributions.
        cost_basis = CostBasisTracker()
        for account_id, account in self.accounts.items():
            if account.tax_treatment == "taxable":
                cost_basis.set_basis(account_id, account.balance)

        rates = self.scenario.economic.get_rate(scenario_name)
        withdrawal_engine = WithdrawalEngine(self.accounts, cost_basis)

        max_year = (self.scenario.primary.birth_date.year
                    + self.scenario.primary.longevity_age + 1)

        for year in range(self.start_year, max_year):
            primary_age = year - self.scenario.primary.birth_date.year
            spouse_age = year - self.scenario.spouse.birth_date.year

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
                    base_rate = account.growth_rate

                if return_volatility > 0:
                    actual_rate = random.gauss(base_rate, return_volatility)
                else:
                    actual_rate = base_rate

                growth = balance * actual_rate
                balances[account_id] = balance + growth

                # Update cost basis for taxable accounts with growth
                if account.tax_treatment == "taxable":
                    current_basis = cost_basis.get_basis(account_id, 0.0)
                    cost_basis.set_basis(account_id, current_basis + growth)

            # --- Step 2: Employee contributions + employer match ---
            primary_retired = self._is_retired(year, self.scenario.primary)
            spouse_retired = self._is_retired(year, self.scenario.spouse)

            if not primary_retired or not spouse_retired:
                # At least one person is still working — allow contributions
                contribs = withdrawal_engine.contribute(balances, year)
                total_contributions += sum(contribs.values())

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
            expense_data = self.calculate_annual_expenses(year, scenario_name)
            annual_expenses = expense_data["total"]

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
            ordinary = annual_income  # W-2 wages + SS (simplified: full SS taxable)
            capital_gains = 0.0
            tax_free = 0.0
            for w in withdrawals:
                if w.tax_treatment == "ordinary":
                    ordinary += w.taxable_amount
                elif w.tax_treatment == "capital_gains":
                    capital_gains += w.capital_gain
                elif w.tax_treatment == "tax_free":
                    tax_free += w.amount

            total = ordinary + capital_gains + tax_free
            taxable_income = TaxableIncome(
                ordinary=ordinary,
                capital_gains=capital_gains,
                tax_free=tax_free,
                total=total,
            )

            # --- Step 7: Taxes ---
            taxes = self.calculate_taxes(year, taxable_income, scenario_name)
            total_taxes += taxes

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
            net_worth = total_assets - total_liabs

            if net_worth > peak_nw:
                peak_nw = net_worth

            if net_worth <= 0 and out_of_savings_year is None:
                out_of_savings_year = year

        final_nw = sum(balances.values())
        success = (final_nw > self.scenario.legacy_goal
                   and out_of_savings_year is None)

        return {
            "success": success,
            "final_net_worth": final_nw,
            "peak_net_worth": peak_nw,
            "lifetime_taxes": total_taxes,
            "lifetime_ss": total_ss,
            "lifetime_contributions": total_contributions,
            "out_of_savings_year": out_of_savings_year,
        }

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

        max_year = (self.scenario.primary.birth_date.year
                    + self.scenario.primary.longevity_age + 1)

        for year in range(self.start_year, max_year):
            primary_age = year - self.scenario.primary.birth_date.year
            spouse_age = year - self.scenario.spouse.birth_date.year

            if (primary_age > self.scenario.primary.longevity_age
                    and spouse_age > self.scenario.spouse.longevity_age):
                break

            income = self.calculate_annual_income(year, scenario_name)
            expenses = self.calculate_annual_expenses(year, scenario_name)

            # Build TaxableIncome (simplified — all income as ordinary
            # for deterministic projection; real sim handles this properly)
            ti = TaxableIncome(
                ordinary=income["total"],
                capital_gains=0.0,
                tax_free=0.0,
                total=income["total"],
            )
            taxes = self.calculate_taxes(year, ti, scenario_name)
            net_worth = self.calculate_net_worth(year, scenario_name)

            projections.append({
                "year": year,
                "primary_age": primary_age,
                "spouse_age": spouse_age,
                "income": income["total"],
                "income_by_source": income["by_source"],
                "expenses": expenses["total"],
                "expenses_by_category": expenses["by_category"],
                "taxes": taxes,
                "net_cash_flow": income["total"] - expenses["total"] - taxes,
                "net_worth": net_worth["net_worth"],
                "total_assets": net_worth["total_assets"],
                "total_liabilities": net_worth["total_liabilities"],
            })

        return projections
