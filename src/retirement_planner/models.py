"""
Data models for the retirement planner.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import date
from enum import Enum
import json


class MonetaryConvention(Enum):
    """Whether simulation values are expressed in nominal or real dollars.

    NOMINAL — All values are in year-of-production dollars.  Expenses,
    income, and investment returns inflate with the general price level.

    REAL — All values are in base-year (purchasing-power) dollars.
    Expenses stay flat in real terms; investment returns are
    inflation-adjusted.  Taxes are computed by temporarily converting
    to nominal so that IRS bracket thresholds remain correct.
    """
    NOMINAL = "nominal"   # All values in year-of dollars
    REAL = "real"         # All values in base-year dollars


@dataclass
class AssetAllocation:
    """Asset allocation between equity and bonds.

    equity_pct + bond_pct should sum to 1.0.
    """
    equity_pct: float = 1.0
    bond_pct: float = 0.0

    def __post_init__(self):
        for field_name, value in (
            ("equity_pct", self.equity_pct),
            ("bond_pct", self.bond_pct),
        ):
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"{field_name} ({value}) must be between 0.0 and 1.0"
                )
        # Allow minor floating-point drift
        if abs(self.equity_pct + self.bond_pct - 1.0) > 0.01:
            raise ValueError(
                f"equity_pct ({self.equity_pct}) + bond_pct ({self.bond_pct}) "
                f"must sum to 1.0"
            )


@dataclass
class GlidepathConfig:
    """Age-based equity/bond glidepath with optional bond tent.

    The glidepath defines how asset allocation shifts from equity-heavy
    (younger) to bond-heavy (older).  A "bond tent" further increases
    bond allocation around retirement to reduce sequence-of-returns risk.

    Default schedule (interpolated between anchor points):
        age 30 → 90% equity, age 40 → 80%, age 50 → 70%,
        age 60 → 60%, age 70 → 50%, age 80 → 40%

    Bond tent: during [retirement_age - pre_retirement_years,
    retirement_age + post_retirement_years], equity is held at
    tent_equity_pct instead of the normal glidepath value.  After the
    tent window, allocation gradually returns to the normal glidepath
    over ``tent_ramp_years``.
    """
    # Age → equity fraction mapping (interpolated linearly)
    equity_by_age: Dict[int, float] = field(default_factory=lambda: {
        30: 0.90,
        40: 0.80,
        50: 0.70,
        60: 0.60,
        70: 0.50,
        80: 0.40,
    })
    # Bond tent parameters
    pre_retirement_years: int = 5
    post_retirement_years: int = 5
    tent_equity_pct: float = 0.30  # 30% equity during tent
    tent_ramp_years: int = 3  # Years to ramp back after tent

    def __post_init__(self):
        if not self.equity_by_age:
            raise ValueError("equity_by_age must contain at least one age anchor")
        for age, equity in self.equity_by_age.items():
            if not isinstance(age, int) or age < 0:
                raise ValueError(f"glidepath age {age!r} must be a non-negative integer")
            if not 0.0 <= equity <= 1.0:
                raise ValueError(f"equity at age {age} ({equity}) must be between 0 and 1")
        if self.pre_retirement_years < 0 or self.post_retirement_years < 0:
            raise ValueError("glidepath retirement windows must be non-negative")
        if self.tent_ramp_years < 0:
            raise ValueError("tent_ramp_years must be non-negative")
        if not 0.0 <= self.tent_equity_pct <= 1.0:
            raise ValueError("tent_equity_pct must be between 0 and 1")


@dataclass
class Person:
    """Profile for a person."""
    name: str
    birth_date: date
    retirement_date: date
    longevity_age: int = 90
    social_security_benefit: float = 0.0
    ss_claiming_age: int = 67
    coverage_type: str = "auto"  # "auto", "employer", "aca", "medicare", "none"

    def coverage_at_age(self, age: int) -> str:
        """Determine healthcare coverage type for this person.

        If coverage_type is "auto", defaults to Medicare when age >= 65,
        otherwise ACA.  Explicit values ("employer", "aca", "medicare",
        "none") override the age-based default.
        """
        if self.coverage_type != "auto":
            return self.coverage_type
        if age >= 65:
            return "medicare"
        return "aca"


@dataclass
class Account:
    """Individual financial account."""
    id: str
    name: str
    account_type: str  # 401k, roth_ira, trad_ira, brokerage, hsa, checking, real_estate, vehicle, other
    tax_treatment: str  # pre_tax, roth, taxable, tax_exempt
    balance: float
    growth_rate: float = 0.088
    growth_rate_optimistic: float = 0.1056
    growth_rate_pessimistic: float = 0.070
    monthly_contribution: float = 0.0  # Legacy — superseded by cash-flow allocation
    employer_match: float = 0.0
    employer_match_limit: float = 0.0
    # Cash-flow savings allocation: lower priority number = funded first.
    # 0 = no auto-contribution from surplus savings.
    contribution_priority: int = 0
    # Max employee contribution per year (0 = unlimited).
    annual_contribution_cap: float = 0.0
    is_depreciating: bool = False
    liquid: bool = True
    asset_class: Optional[str] = None  # "equity", "bond", "mixed", or None (auto)
    expense_ratio: float = 0.0  # Annual fee as decimal (e.g., 0.001 = 0.1%)
    equity_pct: Optional[float] = None  # None = use glidepath default
    owner: str = "primary"  # Legacy configs default to the primary person.

    def project_balance(self, years: int, rate: float) -> float:
        return self.balance * (1 + rate) ** years


@dataclass
class IncomeStream:
    """Recurring income source."""
    id: str
    name: str
    owner: str
    monthly_amount: float
    start_date: date
    end_date: date
    growth_rate: float = 0.0
    is_w2: bool = True
    is_passive: bool = False
    is_ss: bool = False
    goes_to_account: str = ""
    # Enhanced comp fields (optional — legacy monthly_amount still works)
    base_salary: Optional[dict] = None   # {"annual": N, "growth_rate": N}
    bonus: Optional["Bonus"] = None
    equity: Optional["EquityComp"] = None


@dataclass
class RSUGrant:
    """A single RSU grant with its vesting schedule."""
    id: str
    grant_date: date
    total_shares: float
    vesting_pattern: str        # "cliff_quarterly" | "quarterly" | "monthly"
    cliff_shares: float = 0    # shares at cliff vest
    periodic_shares: float = 0 # shares per period after cliff
    cliff_date: Optional[date] = None
    cliff_replaces_first_vest: bool = False  # cliff + first quarterly, or cliff only?
    status: str = "active"     # "active" | "forecasted" | "cancelled"


@dataclass
class RefresherPolicy:
    """Rules for generating future grants automatically."""
    annual_shares: float
    grant_month: int            # month of year new grant arrives (1-12)
    vesting_pattern: str        # "quarterly" | "monthly"
    vesting_delay_months: int = 3  # months after grant before first vest
    start_year: int = 0
    end_year: int = 0           # typically retirement year
    growth_rate: float = 0.0    # annual growth in grant size


@dataclass
class Bonus:
    """Annual bonus configuration."""
    annual: float = 0.0
    growth_rate: float = 0.0
    payment_month: int = 3      # month bonus lands (1-12)


@dataclass
class EquityComp:
    """Full equity compensation model for one employer."""
    ticker: str = ""
    current_price: float = 0.0
    price_source: str = "manual"  # "manual" only for v1
    grants: List[RSUGrant] = field(default_factory=list)
    refreshers: Optional[RefresherPolicy] = None
    end_date: Optional[date] = None    # job termination — stops all vests
    sell_to_cover: bool = True         # sell shares at vest to cover taxes
    is_taxable: bool = True
    goes_to_account: str = ""          # where vested cash lands


@dataclass
class Expense:
    """Recurring or one-time expense."""
    id: str
    name: str
    monthly_amount: float
    start_date: date
    end_date: date
    growth_rate: float = 0.0
    real_growth_rate: float = 0.0  # real (inflation-adjusted) growth per year
    is_one_time: bool = False
    one_time_amount: float = 0.0
    one_time_date: Optional[date] = None
    category: str = "general"
    is_must_spend: bool = True
    min_reduction: float = 0.0  # Maximum % reduction in stress scenarios (0-1)

@dataclass
class AgeEvent:
    """Age-triggered expense modification."""
    trigger_age: int
    expense_id: str  # Which expense to modify
    new_monthly_amount: Optional[float] = None  # None = keep current
    duration_years: int = -1  # -1 = permanent



@dataclass
class Mortgage:
    """Mortgage or loan."""
    id: str
    name: str
    property_id: str
    balance: float
    interest_rate: float
    monthly_payment: float
    start_date: date
    end_date: date
    is_tax_deductible: bool = True


@dataclass
class Windfall:
    """One-time lump sum event."""
    id: str
    name: str
    amount: float
    date: date
    goes_to_account: str = ""
    is_taxable: bool = True


@dataclass
class HousingEvent:
    """Housing purchase/sale event.

    A trade-up is modeled as a single event with both sale_price and
    purchase_price set.  The sale pays off the mortgage(s) secured by
    *property_id* and routes net proceeds to *goes_to_account*; the
    purchase funds the down payment from *funding_account*, adds the new
    property value, and registers a new amortizing mortgage.
    """
    id: str
    name: str
    event_date: date
    sale_price: float = 0.0
    purchase_price: float = 0.0
    down_payment: float = 0.0
    mortgage_amount: float = 0.0
    mortgage_rate: float = 0.05
    mortgage_term_years: int = 30
    property_id: str = ""           # account id of the property sold/bought
    goes_to_account: str = "joint_brokerage"
    funding_account: str = "joint_brokerage"
    new_mortgage_id: str = ""


@dataclass
class RothConversion:
    """Planned Roth conversion."""
    id: str
    name: str
    source_account: str
    target_account: str
    start_date: date
    end_date: date
    annual_amount: float


@dataclass
class RolloverEvent:
    """One-time pre-tax rollover (e.g. 401(k) -> traditional IRA).

    Moves the full source balance to the target on *event_date*, so
    later Roth conversion ladders can draw from the aggregated IRA.
    """
    id: str
    name: str
    event_date: date
    source_account: str
    target_account: str


@dataclass
class SocialSecurity:
    """Social Security configuration."""
    # Primary person
    primary_benefit_at_67: float = 3000  # Monthly benefit at age 67
    primary_claiming_age: int = 67
    # Spouse
    spouse_benefit_at_67: float = 2500
    spouse_claiming_age: int = 67
    # COLA
    cola_rate: float = 0.0254  # Tied to inflation


@dataclass
class EconomicAssumptions:
    """Macroeconomic rates with optimistic/pessimistic ranges.

    Capital market assumptions:
    - equity_real_return: long-run real equity return (default 6%)
    - bond_real_return: long-run real bond return (default 2.5%)
    These replace the old hardcoded bond_rate=0.01 and per-account
    growth_rate as the source of truth for investment returns.
    """
    general_inflation: float = 0.0254
    general_inflation_optimistic: float = 0.0203
    general_inflation_pessimistic: float = 0.0305
    
    ss_cola: float = 0.0254
    ss_cola_optimistic: float = 0.0203
    ss_cola_pessimistic: float = 0.0305
    
    medical_inflation: float = 0.0336
    medical_inflation_optimistic: float = 0.0269
    medical_inflation_pessimistic: float = 0.0403
    
    housing_appreciation: float = 0.044
    housing_appreciation_optimistic: float = 0.0528
    housing_appreciation_pessimistic: float = 0.0352

    # Capital market assumptions (real, pre-tax)
    equity_real_return: float = 0.06
    equity_real_return_optimistic: float = 0.08
    equity_real_return_pessimistic: float = 0.04
    bond_real_return: float = 0.025
    bond_real_return_optimistic: float = 0.035
    bond_real_return_pessimistic: float = 0.015
    
    def get_rate(self, scenario: str = "mean") -> Dict[str, float]:
        if scenario == "optimistic":
            return {
                "general_inflation": self.general_inflation_optimistic,
                "ss_cola": self.ss_cola_optimistic,
                "medical_inflation": self.medical_inflation_optimistic,
                "housing_appreciation": self.housing_appreciation_optimistic,
                "equity_real_return": self.equity_real_return_optimistic,
                "bond_real_return": self.bond_real_return_optimistic,
            }
        elif scenario == "pessimistic":
            return {
                "general_inflation": self.general_inflation_pessimistic,
                "ss_cola": self.ss_cola_pessimistic,
                "medical_inflation": self.medical_inflation_pessimistic,
                "housing_appreciation": self.housing_appreciation_pessimistic,
                "equity_real_return": self.equity_real_return_pessimistic,
                "bond_real_return": self.bond_real_return_pessimistic,
            }
        else:
            return {
                "general_inflation": self.general_inflation,
                "ss_cola": self.ss_cola,
                "medical_inflation": self.medical_inflation,
                "housing_appreciation": self.housing_appreciation,
                "equity_real_return": self.equity_real_return,
                "bond_real_return": self.bond_real_return,
            }


@dataclass
class Scenario:
    """A complete retirement scenario."""
    name: str
    description: str
    primary: Person
    spouse: Person
    economic: EconomicAssumptions
    accounts: List[Account]
    income_streams: List[IncomeStream]
    expenses: List[Expense]
    mortgages: List[Mortgage]
    windfalls: List[Windfall] = field(default_factory=list)
    housing_events: List[HousingEvent] = field(default_factory=list)
    roth_conversions: List[RothConversion] = field(default_factory=list)
    rollover_events: List[RolloverEvent] = field(default_factory=list)
    age_events: List[AgeEvent] = field(default_factory=list)
    social_security: SocialSecurity = field(default_factory=SocialSecurity)
    glidepath: Optional[GlidepathConfig] = None
    withdrawal_strategy: str = "fixed"  # fixed, guardrails, dynamic, percent_of_portfolio, floor_ceiling
    withdrawal_rate: float = 0.04       # For percent-of-portfolio strategy
    guardrail_floor_pct: float = 0.90   # 90% of base spending floor
    guardrail_ceiling_pct: float = 1.10  # 110% of base spending ceiling
    legacy_goal: float = 2_000_000
    state: str = "CA"
    family_size: int = 2
    # Explicit savings priority order (account ids, funded first → last).
    # Accounts not listed get contribution_priority=0 (no auto-contribution)
    # unless they set contribution_priority explicitly or use the legacy
    # monthly_contribution field.
    savings_order: List[str] = field(default_factory=list)
    # Monetary convention: NOMINAL (all values in year-of dollars) or
    # REAL (all values in base-year purchasing-power dollars).
    monetary_convention: MonetaryConvention = MonetaryConvention.REAL

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "name": self.name,
            "description": self.description,
            "primary": {
                "name": self.primary.name,
                "birth_date": self.primary.birth_date.isoformat(),
                "retirement_date": self.primary.retirement_date.isoformat(),
                "longevity_age": self.primary.longevity_age,
            },
            "spouse": {
                "name": self.spouse.name,
                "birth_date": self.spouse.birth_date.isoformat(),
                "retirement_date": self.spouse.retirement_date.isoformat(),
                "longevity_age": self.spouse.longevity_age,
            },
            "legacy_goal": self.legacy_goal,
            "state": self.state,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class TaxableIncome:
    """Carries income breakdown by tax treatment for accurate tax calculation.

    Each field represents annual amounts.  The engine populates this
    from salary, account withdrawals, Social Security, and other sources
    before passing it to ``calculate_taxes()``.
    """
    ordinary: float = 0.0       # W-2 wages, pre-tax 401k/IRA withdrawals, interest, SS (taxable portion)
    capital_gains: float = 0.0  # Long-term capital gains from taxable brokerage sales
    tax_free: float = 0.0       # Roth withdrawals, HSA qualified distributions
    total: float = 0.0          # Convenience total (set by caller)
