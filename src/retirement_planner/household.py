"""
Household lifecycle, mortality, survivor transitions, and healthcare (Phase 4).

Covers:
- Mortality tables → sample household lifetimes
- Survivor transitions: filing status, SS survivor benefits, expense shifts
- Healthcare lifecycle: pre-65 ACA → Medicare B/D → IRMAA → Medigap/MA → LTC
- Spending phases: go-go / slow-go / no-go
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .tax_law import FilingStatus, determine_filing_status


# ---------------------------------------------------------------------------
# Mortality table — SSA 2023 Period Life Table (2026 Trustees Report)
# ---------------------------------------------------------------------------
# Age → q(x): probability of DYING within one year at exact age x.
# Source: https://www.ssa.gov/oact/STATS/table4c6.html — the 2023 period
# life table for the Social Security area population, used in the 2026 TR.
# Full year-by-year data, ages 0-119, separated by sex. These replace the
# earlier approximate 5-year-bucket tables.
_SSA_QX_MALE: Dict[int, float] = {
    0: 0.006015, 1: 0.000479, 2: 0.000320, 3: 0.000249, 4: 0.000194,
    5: 0.000159, 6: 0.000137, 7: 0.000125, 8: 0.000120, 9: 0.000120,
    10: 0.000125, 11: 0.000140, 12: 0.000173, 13: 0.000233, 14: 0.000327,
    15: 0.000463, 16: 0.000634, 17: 0.000819, 18: 0.000999, 19: 0.001138,
    20: 0.001235, 21: 0.001315, 22: 0.001378, 23: 0.001439, 24: 0.001509,
    25: 0.001595, 26: 0.001685, 27: 0.001783, 28: 0.001876, 29: 0.001970,
    30: 0.002085, 31: 0.002202, 32: 0.002308, 33: 0.002407, 34: 0.002490,
    35: 0.002577, 36: 0.002665, 37: 0.002764, 38: 0.002864, 39: 0.002987,
    40: 0.003115, 41: 0.003253, 42: 0.003419, 43: 0.003600, 44: 0.003777,
    45: 0.003931, 46: 0.004073, 47: 0.004245, 48: 0.004477, 49: 0.004795,
    50: 0.005126, 51: 0.005496, 52: 0.005917, 53: 0.006404, 54: 0.006923,
    55: 0.007491, 56: 0.008173, 57: 0.008938, 58: 0.009714, 59: 0.010494,
    60: 0.011337, 61: 0.012232, 62: 0.013196, 63: 0.014229, 64: 0.015316,
    65: 0.016455, 66: 0.017574, 67: 0.018735, 68: 0.019981, 69: 0.021366,
    70: 0.022903, 71: 0.024615, 72: 0.026504, 73: 0.028648, 74: 0.031071,
    75: 0.033802, 76: 0.037010, 77: 0.041158, 78: 0.045461, 79: 0.050346,
    80: 0.055633, 81: 0.061757, 82: 0.068358, 83: 0.075420, 84: 0.083364,
    85: 0.092680, 86: 0.103459, 87: 0.115502, 88: 0.129018, 89: 0.143810,
    90: 0.159458, 91: 0.176551, 92: 0.195360, 93: 0.216286, 94: 0.238799,
    95: 0.262268, 96: 0.286291, 97: 0.310944, 98: 0.332325, 99: 0.349036,
    100: 0.366568, 101: 0.384960, 102: 0.404252, 103: 0.424488, 104: 0.445712,
    105: 0.467998, 106: 0.491398, 107: 0.515968, 108: 0.541766, 109: 0.568854,
    110: 0.597297, 111: 0.627162, 112: 0.658520, 113: 0.691446, 114: 0.726018,
    115: 0.762319, 116: 0.800435, 117: 0.840457, 118: 0.882480, 119: 0.926604,
}

_SSA_QX_FEMALE: Dict[int, float] = {
    0: 0.005125, 1: 0.000392, 2: 0.000229, 3: 0.000188, 4: 0.000155,
    5: 0.000133, 6: 0.000115, 7: 0.000105, 8: 0.000100, 9: 0.000098,
    10: 0.000101, 11: 0.000111, 12: 0.000126, 13: 0.000152, 14: 0.000188,
    15: 0.000229, 16: 0.000273, 17: 0.000323, 18: 0.000372, 19: 0.000410,
    20: 0.000441, 21: 0.000476, 22: 0.000513, 23: 0.000546, 24: 0.000582,
    25: 0.000609, 26: 0.000641, 27: 0.000683, 28: 0.000740, 29: 0.000808,
    30: 0.000878, 31: 0.000947, 32: 0.001018, 33: 0.001089, 34: 0.001154,
    35: 0.001209, 36: 0.001263, 37: 0.001347, 38: 0.001438, 39: 0.001533,
    40: 0.001643, 41: 0.001742, 42: 0.001845, 43: 0.001954, 44: 0.002075,
    45: 0.002187, 46: 0.002306, 47: 0.002438, 48: 0.002595, 49: 0.002791,
    50: 0.003030, 51: 0.003288, 52: 0.003554, 53: 0.003847, 54: 0.004172,
    55: 0.004532, 56: 0.004923, 57: 0.005365, 58: 0.005815, 59: 0.006333,
    60: 0.006923, 61: 0.007555, 62: 0.008220, 63: 0.008881, 64: 0.009514,
    65: 0.010188, 66: 0.010880, 67: 0.011659, 68: 0.012543, 69: 0.013581,
    70: 0.014769, 71: 0.016153, 72: 0.017705, 73: 0.019495, 74: 0.021533,
    75: 0.023846, 76: 0.026458, 77: 0.029700, 78: 0.033135, 79: 0.036982,
    80: 0.041183, 81: 0.045959, 82: 0.051282, 83: 0.057262, 84: 0.064107,
    85: 0.071752, 86: 0.080490, 87: 0.090566, 88: 0.102204, 89: 0.115178,
    90: 0.129176, 91: 0.144229, 92: 0.160353, 93: 0.177635, 94: 0.196502,
    95: 0.216846, 96: 0.238750, 97: 0.261359, 98: 0.283899, 99: 0.306491,
    100: 0.329680, 101: 0.353333, 102: 0.377300, 103: 0.401416, 104: 0.425501,
    105: 0.451031, 106: 0.478092, 107: 0.506778, 108: 0.537185, 109: 0.568854,
    110: 0.597297, 111: 0.627162, 112: 0.658520, 113: 0.691446, 114: 0.726018,
    115: 0.762319, 116: 0.800435, 117: 0.840457, 118: 0.882480, 119: 0.926604,
}

# Oldest tabulated age; sampling clamps here (everyone dies by 119).
MAX_AGE = 119


def _qx(table: Dict[int, float], age: float) -> float:
    """Year-by-year death probability q(x); clamps at the table edges."""
    if age <= 0:
        return table[0]
    if age >= MAX_AGE:
        return table[MAX_AGE]
    return table[int(age)]


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
        """Probability of surviving one more year from given age (1 - q(x))."""
        table = _SSA_QX_MALE if is_male else _SSA_QX_FEMALE
        q = _qx(table, age)
        p = 1.0 - q
        # Boost: increase survival probability (caps at 0.999)
        p_boosted = min(0.999, p * self.longevity_boost)
        return p_boosted

    def expected_remaining_years(self, age: float, is_male: bool = True) -> float:
        """Expected remaining years of life (E[remaining]).

        Returns the *complete* life expectancy (curtate sum + 0.5), matching
        the SSA period life table's published "Life expectancy" column.
        """
        total = 0.0
        p_survive = 1.0
        for y in range(100):
            current_age = age + y
            p_year = self.survival_probability(current_age, is_male)
            p_survive *= p_year
            total += p_survive
        return total + 0.5

    def sample_death_age(
        self,
        current_age: float,
        is_male: bool = True,
        max_age: int = MAX_AGE,
        rng=None,
    ) -> int:
        """Sample a death age using Monte Carlo.

        Returns the age at which the person dies (inclusive). If *rng* (a
        NumPy Generator) is provided, draws are reproducible; otherwise the
        ``random`` stdlib module is used.
        """
        draw = rng.random if rng is not None else random.random
        age = int(current_age)
        while age < max_age:
            p = self.survival_probability(age, is_male)
            if draw() > p:
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


def stochastic_alive_snapshot(
    year: int,
    dependents,
    primary_age: float,
    spouse_age: float,
) -> "SurvivorSnapshot":
    """Synthetic 'both alive' snapshot for the stochastic-mortality MC path.

    The stochastic path models the household as one unit that dies together
    at a single sampled year (see the stochastic mortality plan). Every
    modeled year both spouses are alive (MFJ); there are no survivor
    transitions, no spousal rollover, and no estate tax. The run simply
    ends once the sampled death age is passed.
    """
    medicare_adult_count = (
        (1 if primary_age >= 65 else 0) + (1 if spouse_age >= 65 else 0))
    aca_family_size = 2 + active_dependent_count(year, dependents)
    return SurvivorSnapshot(
        year=year,
        primary_alive=True,
        spouse_alive=True,
        survivor=None,
        filing_status=FilingStatus.MFJ,
        is_primary_death_year=False,
        is_spouse_death_year=False,
        is_first_death_year=False,
        is_second_death_year=False,
        estate_event=False,
        aca_family_size=aca_family_size,
        medicare_adult_count=medicare_adult_count,
        first_death_year=None,
        second_death_year=None,
    )


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

    # ACA family size: ACA-eligible (under-65, ACA coverage) living adults
    # plus active dependents.  Medicare-covered adults: living adults at
    # Medicare age with Medicare coverage.  The two counts are derived
    # separately (KTD5) and stay coverage-aware so coverage_type and the
    # pre-Medicare gate are honored.
    aca_family_size = (
        sum(1 for person, alive in ((primary, primary_alive),
                                    (spouse, spouse_alive))
            if alive
            and (year - person.birth_date.year) < 65
            and person.coverage_at_age(year - person.birth_date.year) == "aca")
        + active_dependent_count(year, dependents))
    medicare_adult_count = sum(
        1 for person, alive in ((primary, primary_alive),
                                (spouse, spouse_alive))
        if alive
        and (year - person.birth_date.year) >= 65
        and person.coverage_at_age(year - person.birth_date.year) == "medicare")


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


def rollover_pretax_ownership(
    owner_map: Dict[str, str],
    accounts,
    deceased: str,
    survivor: str,
) -> Dict[str, str]:
    """Reassign eligible pre-tax account ownership to the survivor.

    Mutates only the local *owner_map* (never the shared ``Account``
    objects) so Monte Carlo runs do not leak ownership across iterations
    (R7).  Eligible accounts are those the engine's RMD path recognizes
    as pre-tax; accounts already owned by the survivor are left untouched.
    """
    for account_id, account in accounts.items():
        if account.tax_treatment != "pre_tax":
            continue
        current = owner_map.get(
            account_id, (account.owner or "primary").lower())
        if current == deceased:
            owner_map[account_id] = survivor
    return owner_map


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
