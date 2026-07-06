"""
Data models for the retirement planner.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import date
import json


@dataclass
class Person:
    """Profile for a person."""
    name: str
    birth_date: date
    retirement_date: date
    longevity_age: int = 90
    social_security_benefit: float = 0.0
    ss_claiming_age: int = 67


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
    monthly_contribution: float = 0.0
    employer_match: float = 0.0
    employer_match_limit: float = 0.0
    is_depreciating: bool = False
    liquid: bool = True
    
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


@dataclass
class Expense:
    """Recurring or one-time expense."""
    id: str
    name: str
    monthly_amount: float
    start_date: date
    end_date: date
    growth_rate: float = 0.0
    is_one_time: bool = False
    one_time_amount: float = 0.0
    one_time_date: Optional[date] = None
    category: str = "general"
    is_must_spend: bool = True


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
    """Housing purchase/sale event."""
    id: str
    name: str
    event_date: date
    sale_price: float = 0.0
    purchase_price: float = 0.0
    down_payment: float = 0.0
    mortgage_amount: float = 0.0
    mortgage_rate: float = 0.05
    mortgage_term_years: int = 30


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
class SocialSecurity:
    """Social Security configuration."""
    # Primary
    primary_benefit_at_67: float = 3000  # Monthly benefit
    primary_claiming_age: int = 67
    # Spouse
    spouse_benefit_at_67: float = 2500
    spouse_claiming_age: int = 67
    # COLA
    cola_rate: float = 0.0254  # Tied to inflation


@dataclass
class EconomicAssumptions:
    """Macroeconomic rates with optimistic/pessimistic ranges."""
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
    
    def get_rate(self, scenario: str = "mean") -> Dict[str, float]:
        if scenario == "optimistic":
            return {
                "general_inflation": self.general_inflation_optimistic,
                "ss_cola": self.ss_cola_optimistic,
                "medical_inflation": self.medical_inflation_optimistic,
                "housing_appreciation": self.housing_appreciation_optimistic,
            }
        elif scenario == "pessimistic":
            return {
                "general_inflation": self.general_inflation_pessimistic,
                "ss_cola": self.ss_cola_pessimistic,
                "medical_inflation": self.medical_inflation_pessimistic,
                "housing_appreciation": self.housing_appreciation_pessimistic,
            }
        else:
            return {
                "general_inflation": self.general_inflation,
                "ss_cola": self.ss_cola,
                "medical_inflation": self.medical_inflation,
                "housing_appreciation": self.housing_appreciation,
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
    social_security: SocialSecurity = field(default_factory=SocialSecurity)
    legacy_goal: float = 2_000_000
    state: str = "CA"
    
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
