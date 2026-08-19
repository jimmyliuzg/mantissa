"""
Household lifecycle, mortality, survivor transitions, and healthcare (Phase 4).

Covers:
- Mortality tables → sample household lifetimes
- Survivor transitions: filing status, SS survivor benefits, expense shifts
- Healthcare lifecycle: pre-65 ACA → Medicare B/D → IRMAA → Medigap/MA → LTC
- Spending phases: go-go / slow-go / no-go
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .tax_law import FilingStatus, determine_filing_status


# ---------------------------------------------------------------------------
# Mortality table (SSA Period Life Table, simplified)
# ---------------------------------------------------------------------------
# Age → probability of surviving one more year
# Source: SSA 2020 period life table (approximate)
_MORTALITY_TABLE_MALE: Dict[int, float] = {
    30: 0.9972, 35: 0.9965, 40: 0.9954, 45: 0.9936,
    50: 0.9907, 55: 0.9864, 60: 0.9798, 65: 0.9693,
    70: 0.9530, 75: 0.9282, 80: 0.8898, 85: 0.8340,
    90: 0.7490, 95: 0.6100,
}

_MORTALITY_TABLE_FEMALE: Dict[int, float] = {
    30: 0.9985, 35: 0.9980, 40: 0.9973, 45: 0.9963,
    50: 0.9945, 55: 0.9915, 60: 0.9865, 65: 0.9788,
    70: 0.9663, 75: 0.9466, 80: 0.9168, 85: 0.8680,
    90: 0.7900, 95: 0.6600,
}


def _interpolate_survival(table: Dict[int, float], age: float) -> float:
    """Interpolate survival probability for fractional ages."""
    ages = sorted(table.keys())
    if age <= ages[0]:
        return table[ages[0]]
    if age >= ages[-1]:
        return table[ages[-1]]

    for i in range(len(ages) - 1):
        if ages[i] <= age <= ages[i + 1]:
            t = (age - ages[i]) / (ages[i + 1] - ages[i])
            p1 = table[ages[i]]
            p2 = table[ages[i + 1]]
            return p1 + t * (p2 - p1)
    return table[ages[-1]]


@dataclass
class MortalityModel:
    """Mortality model for a household.

    Uses SSA period life tables with optional longevity boost
    (for planning purposes, many retirees live longer than median).
    """
    primary_male: bool = True
    spouse_male: bool = False
    longevity_boost: float = 1.0  # multiplier on survival probability (1.0 = table, 1.1 = optimistic)

    def survival_probability(self, age: float, is_male: bool = True) -> float:
        """Probability of surviving one more year from given age."""
        table = _MORTALITY_TABLE_MALE if is_male else _MORTALITY_TABLE_FEMALE
        p = _interpolate_survival(table, age)
        # Boost: increase survival probability (caps at 0.999)
        p_boosted = min(0.999, p * self.longevity_boost)
        return p_boosted

    def expected_remaining_years(self, age: float, is_male: bool = True) -> float:
        """Expected remaining years of life (E[remaining])."""
        total = 0.0
        p_survive = 1.0
        for y in range(100):
            current_age = age + y
            p_year = self.survival_probability(current_age, is_male)
            p_survive *= p_year
            total += p_survive
        return total

    def sample_death_age(
        self,
        current_age: float,
        is_male: bool = True,
        max_age: int = 105,
    ) -> int:
        """Sample a death age using Monte Carlo.

        Returns the age at which the person dies (inclusive).
        """
        import random
        age = current_age
        while age < max_age:
            p = self.survival_probability(age, is_male)
            if random.random() > p:
                return int(age)
            age += 1
        return max_age


@dataclass
class HouseholdLifetime:
    """Result of sampling household lifetimes."""
    primary_death_age: int
    spouse_death_age: int
    years_together: int         # years both alive from now
    primary_solo_years: int     # years primary alive after spouse death
    spouse_solo_years: int      # years spouse alive after primary death

    @property
    def primary_longer(self) -> bool:
        return self.primary_death_age > self.spouse_death_age

    @property
    def spouse_longer(self) -> bool:
        return self.spouse_death_age > self.primary_death_age


def sample_household_lifetimes(
    primary_age: float,
    spouse_age: float,
    primary_male: bool = True,
    spouse_male: bool = False,
    longevity_boost: float = 1.0,
    num_simulations: int = 1000,
) -> Tuple[float, float, List[HouseholdLifetime]]:
    """Sample household lifetimes and return statistics.

    Returns:
        (median_primary_age, median_spouse_age, list_of_lifetimes)
    """
    model = MortalityModel(
        primary_male=primary_male,
        spouse_male=spouse_male,
        longevity_boost=longevity_boost,
    )

    lifetimes = []
    primary_ages = []
    spouse_ages = []

    for _ in range(num_simulations):
        p_death = model.sample_death_age(primary_age, primary_male)
        s_death = model.sample_death_age(spouse_age, spouse_male)
        primary_ages.append(p_death)
        spouse_ages.append(s_death)

        years_together = max(0, min(p_death, s_death) - int(max(primary_age, spouse_age)))
        p_solo = max(0, p_death - s_death) if p_death > s_death else 0
        s_solo = max(0, s_death - p_death) if s_death > p_death else 0

        lifetimes.append(HouseholdLifetime(
            primary_death_age=p_death,
            spouse_death_age=s_death,
            years_together=years_together,
            primary_solo_years=p_solo,
            spouse_solo_years=s_solo,
        ))

    primary_ages.sort()
    spouse_ages.sort()
    median_p = primary_ages[len(primary_ages) // 2]
    median_s = spouse_ages[len(spouse_ages) // 2]

    return median_p, median_s, lifetimes


# ---------------------------------------------------------------------------
# Survivor transitions
# ---------------------------------------------------------------------------
@dataclass
class SurvivorTransition:
    """What changes when a spouse dies."""
    year: int
    deceased: str          # "primary" or "spouse"
    new_filing_status: str  # "MFJ" → "QSS" → "HOH" or "Single"
    ss_benefit_change: float  # change in Social Security (survivor benefit)
    expense_change: float     # change in annual expenses
    irmaa_change: float       # change in IRMAA (if applicable)
    years_until_qss_expiry: int = 0  # QSS available for 2 years


def compute_survivor_transition(
    year_of_death: int,
    current_year: int,
    deceased: str,
    primary_age: int,
    has_dependents: bool,
    ss_primary_annual: float,
    ss_spouse_annual: float,
    household_expenses: float,
) -> SurvivorTransition:
    """Compute the financial impact of a spouse's death.

    Rules:
    - Death year: still MFJ
    - Years 1-2 after death with dependents: QSS (same rates as MFJ)
    - After QSS: HOH (if dependents) or Single (higher brackets, no QSS)
    - SS survivor benefit: higher of own benefit or 100% of deceased's
    - Expenses: typically drop 20-30% (one person instead of two)
    """
    years_since = current_year - year_of_death

    # Filing status
    if years_since == 0:
        filing = "MFJ"
        qss_remaining = 2 if has_dependents else 0
    elif years_since <= 2 and has_dependents:
        filing = "QSS"
        qss_remaining = 2 - years_since
    elif has_dependents:
        filing = "HOH"
        qss_remaining = 0
    else:
        filing = "Single"
        qss_remaining = 0

    # Social Security survivor benefit
    # Survivor gets the higher of their own benefit or 100% of deceased's
    if deceased == "spouse":
        survivor_ss = max(ss_primary_annual, ss_spouse_annual)
    else:
        survivor_ss = max(ss_spouse_annual, ss_primary_annual)
    ss_change = survivor_ss - (ss_primary_annual + ss_spouse_annual) / 2

    # Expense reduction: typically 20-30% for single vs couple
    # Using 25% as midpoint
    expense_reduction = household_expenses * 0.25

    return SurvivorTransition(
        year=year_of_death,
        deceased=deceased,
        new_filing_status=filing,
        ss_benefit_change=ss_change,
        expense_change=-expense_reduction,
        irmaa_change=0,  # Computed separately based on new MAGI
        years_until_qss_expiry=qss_remaining,
    )


# ---------------------------------------------------------------------------
# Deterministic survivor transition source (KTD1)
# ---------------------------------------------------------------------------
# One pure, longevity-derived annual household survivor snapshot shared by
# the deterministic projection and Monte Carlo paths. No stochastic mortality
# and no global randomness: death years come only from configured longevity
# ages (R1). The same rules feed both paths so survivor state and estate
# timing stay consistent (R9).
def configured_death_year(person) -> int:
    """Deterministic death year from birth year + configured longevity age.

    The death year is the person's final *full* modeled year: they are alive
    during it (R2). They are treated as dead beginning the following year.
    """
    return person.birth_date.year + person.longevity_age


def active_dependent_count(year: int, dependents, cutoff_age: int = 26) -> int:
    """Count dependents alive and under *cutoff_age* in *year*.

    First-slice approximation for QSS/HOH qualification (R3) and ACA family
    size (R5). Mirrors :class:`Dependent` semantics (children count while
    under 26).
    """
    if not dependents:
        return 0
    return sum(
        1 for dep in dependents
        if 0 <= (year - dep.birth_date.year) < cutoff_age
    )


@dataclass
class SurvivorSnapshot:
    """Annual household survivor state derived from longevity ages.

    Pure: depends only on configured birth/longevity and dependents. The
    deterministic loop and Monte Carlo path both consume this so transitions
    are auditable and identical (R9).
    """
    year: int
    primary_alive: bool
    spouse_alive: bool
    # Identity of the surviving spouse between deaths; None if both alive
    # (death year inclusive) or both deceased (post-settlement).
    survivor: Optional[str]            # "primary" / "spouse"
    filing_status: FilingStatus
    is_primary_death_year: bool
    is_spouse_death_year: bool
    is_first_death_year: bool
    is_second_death_year: bool
    # Estate is assessed once, at the second configured death year (R8).
    estate_event: bool
    aca_family_size: int               # living adults + active dependents (R5)
    medicare_adult_count: int          # living adults at Medicare age (R5)
    first_death_year: Optional[int]
    second_death_year: Optional[int]


def survivor_snapshot(
    year: int,
    primary,
    spouse,
    dependents=None,
) -> SurvivorSnapshot:
    """Build the longevity-derived survivor snapshot for *year*.

    Death years are ``birth_year + longevity_age``. A person is alive during
    their death year and dead thereafter (R2). Filing status follows the
    existing tax rules via ``determine_filing_status`` (R3): MFJ in the death
    year, then QSS for two years when dependents qualify, then HOH when
    dependents remain or Single otherwise.
    """
    primary_death = configured_death_year(primary)
    spouse_death = configured_death_year(spouse)
    primary_alive = year <= primary_death
    spouse_alive = year <= spouse_death

    equal_deaths = primary_death == spouse_death
    first_death_year = (
        None if equal_deaths else min(primary_death, spouse_death))
    second_death_year = max(primary_death, spouse_death)

    is_primary_death_year = year == primary_death
    is_spouse_death_year = year == spouse_death
    is_first_death_year = (year == first_death_year) and not equal_deaths
    is_second_death_year = (year == second_death_year)
    estate_event = is_second_death_year

    if primary_alive and spouse_alive:
        survivor: Optional[str] = None
    elif primary_alive:
        survivor = "primary"
    elif spouse_alive:
        survivor = "spouse"
    else:
        survivor = None

    has_dependents = active_dependent_count(year, dependents) > 0
    filing_status = determine_filing_status(
        primary_alive=primary_alive,
        spouse_alive=spouse_alive,
        year_of_death_spouse=first_death_year,
        current_year=year,
        has_dependents=has_dependents,
    )

    living_adults = int(primary_alive) + int(spouse_alive)
    aca_family_size = living_adults + active_dependent_count(year, dependents)
    medicare_adult_count = sum(
        1 for person, alive in ((primary, primary_alive),
                                (spouse, spouse_alive))
        if alive and (year - person.birth_date.year) >= 65
    )

    return SurvivorSnapshot(
        year=year,
        primary_alive=primary_alive,
        spouse_alive=spouse_alive,
        survivor=survivor,
        filing_status=filing_status,
        is_primary_death_year=is_primary_death_year,
        is_spouse_death_year=is_spouse_death_year,
        is_first_death_year=is_first_death_year,
        is_second_death_year=is_second_death_year,
        estate_event=estate_event,
        aca_family_size=aca_family_size,
        medicare_adult_count=medicare_adult_count,
        first_death_year=first_death_year,
        second_death_year=second_death_year,
    )


def normalize_filing_status(value) -> FilingStatus:
    """Normalize a string or enum filing status to the ``FilingStatus`` enum.

    Tax calls key brackets/deductions by the enum (KTD8), so every status
    delivered to ``calculate_taxes`` must be normalized first, including the
    housing-event tax path.
    """
    if isinstance(value, FilingStatus):
        return value
    return FilingStatus[str(value).strip().upper()]


# ---------------------------------------------------------------------------
# Healthcare lifecycle
# ---------------------------------------------------------------------------
@dataclass
class HealthcarePhase:
    """A phase of healthcare coverage."""
    id: str
    name: str
    start_age: int
    end_age: int
    monthly_premium: float     # base premium per person
    deductible: float          # annual deductible
    oop_max: float             # annual out-of-pocket max
    coverage_type: str         # "aca", "medicare_ab", "medigap", "ma", "ltc"


# Default healthcare phases (2024 dollars, per person)
DEFAULT_HEALTHCARE_PHASES: List[HealthcarePhase] = [
    HealthcarePhase(
        id="aca", name="ACA Marketplace",
        start_age=0, end_age=64,
        monthly_premium=800, deductible=4000, oop_max=9000,
        coverage_type="aca",
    ),
    HealthcarePhase(
        id="medicare_ab", name="Medicare Part A+B",
        start_age=65, end_age=105,
        monthly_premium=175, deductible=240, oop_max=7500,
        coverage_type="medicare_ab",
    ),
    HealthcarePhase(
        id="medigap", name="Medigap Plan G",
        start_age=65, end_age=105,
        monthly_premium=200, deductible=0, oop_max=2500,
        coverage_type="medigap",
    ),
    HealthcarePhase(
        id="ltc_shock", name="Long-Term Care Event",
        start_age=80, end_age=85,
        monthly_premium=8000, deductible=0, oop_max=480000,
        coverage_type="ltc",
    ),
]


def calculate_healthcare_cost(
    age: int,
    phases: Optional[List[HealthcarePhase]] = None,
    inflation_rate: float = 0.04,
    years_from_base: int = 0,
    irmaa_surcharge_monthly: float = 0.0,
    num_people: int = 2,
) -> float:
    """Calculate annual healthcare cost for a given age.

    Combines active healthcare phases (multiple can overlap, e.g. Medicare + Medigap).
    """
    if phases is None:
        phases = DEFAULT_HEALTHCARE_PHASES

    inflation_factor = (1 + inflation_rate) ** years_from_base
    total = 0.0

    for phase in phases:
        if phase.start_age <= age <= phase.end_age:
            premium = phase.monthly_premium * inflation_factor * 12 * num_people
            total += premium

    # Add IRMAA surcharge (Medicare only)
    if age >= 65:
        total += irmaa_surcharge_monthly * 12 * num_people

    return total


# ---------------------------------------------------------------------------
# Spending phases (go-go / slow-go / no-go)
# ---------------------------------------------------------------------------
@dataclass
class SpendingPhaseProfile:
    """How spending changes through retirement phases."""
    # Go-go years: active travel, hobbies (age 65-75)
    go_go_multiplier: float = 1.15  # 15% above base
    go_go_start_age: int = 65
    go_go_end_age: int = 75

    # Slow-go years: less travel, more home (age 75-85)
    slow_go_multiplier: float = 0.90  # 10% below base
    slow_go_start_age: int = 75
    slow_go_end_age: int = 85

    # No-go years: mostly home, healthcare dominant (age 85+)
    no_go_multiplier: float = 0.70  # 30% below base
    no_go_start_age: int = 85

    def spending_multiplier(self, age: int) -> float:
        """Return the spending multiplier for a given age."""
        if age < self.go_go_start_age:
            return 1.0  # Pre-retirement: base spending
        elif age <= self.go_go_end_age:
            return self.go_go_multiplier
        elif age <= self.slow_go_end_age:
            return self.slow_go_multiplier
        else:
            return self.no_go_multiplier

    def apply(self, base_spending: float, age: int) -> float:
        """Apply spending phase to base spending."""
        return base_spending * self.spending_multiplier(age)


# ---------------------------------------------------------------------------
# Household state machine
# ---------------------------------------------------------------------------
@dataclass
class HouseholdState:
    """Tracks the state of the household through the projection."""
    year: int
    primary_age: float
    spouse_age: float
    primary_alive: bool = True
    spouse_alive: bool = True
    filing_status: str = "MFJ"
    num_dependents: int = 0

    # Healthcare
    healthcare_phase: str = "working"  # "working", "early_retire_aca", "medicare"
    irmaa_surcharge: float = 0.0

    # Social Security
    ss_primary_annual: float = 0.0
    ss_spouse_annual: float = 0.0
    ss_claiming_age: int = 67

    # Spending
    spending_phase: str = "accumulation"  # "accumulation", "go_go", "slow_go", "no_go"

    def advance_year(self, mortality_model: Optional[MortalityModel] = None):
        """Advance the household by one year."""
        self.year += 1
        self.primary_age += 1
        self.spouse_age += 1

        # Check deaths
        if self.primary_alive and mortality_model:
            p = mortality_model.survival_probability(self.primary_age - 1, mortality_model.primary_male)
            import random
            if random.random() > p:
                self.primary_alive = False
                self._handle_death("primary")

        if self.spouse_alive and mortality_model:
            p = mortality_model.survival_probability(self.spouse_age - 1, mortality_model.spouse_male)
            import random
            if random.random() > p:
                self.spouse_alive = False
                self._handle_death("spouse")

        # Update filing status
        self._update_filing_status()

        # Update healthcare phase
        self._update_healthcare_phase()

        # Update spending phase
        self._update_spending_phase()

    def _handle_death(self, who: str):
        """Handle the death of a household member."""
        if who == "primary":
            self.num_dependents = 0  # Simplified
        elif who == "spouse":
            pass  # Primary continues

    def _update_filing_status(self):
        """Update filing status based on household state."""
        if self.primary_alive and self.spouse_alive:
            self.filing_status = "MFJ"
        elif not self.spouse_alive:
            # Primary is surviving spouse
            if self.num_dependents > 0:
                self.filing_status = "QSS"  # For 2 years, then HOH
            else:
                self.filing_status = "Single"
        elif not self.primary_alive:
            # Spouse is surviving
            if self.num_dependents > 0:
                self.filing_status = "HOH"
            else:
                self.filing_status = "Single"

    def _update_healthcare_phase(self):
        """Update healthcare phase based on ages."""
        min_age = min(self.primary_age, self.spouse_age) if self.spouse_alive else self.primary_age
        if min_age < 65:
            self.healthcare_phase = "aca" if not self.primary_alive or self.primary_age < 65 else "working"
        else:
            self.healthcare_phase = "medicare"

    def _update_spending_phase(self):
        """Update spending phase based on age."""
        avg_age = (self.primary_age + (self.spouse_age if self.spouse_alive else self.primary_age)) / 2
        if avg_age < 65:
            self.spending_phase = "accumulation"
        elif avg_age < 75:
            self.spending_phase = "go_go"
        elif avg_age < 85:
            self.spending_phase = "slow_go"
        else:
            self.spending_phase = "no_go"
