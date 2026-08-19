"""Survivor vertical — U1 deterministic household transition contract.

Golden fixtures for the pure, longevity-derived survivor snapshot shared by
the deterministic projection and Monte Carlo paths (KTD1, R1-R3, R9).

These tests characterize the transition source directly. Engine-loop wiring
(SS survivor benefit, expense scaling, ACA/Medicare counts, spousal rollover,
estate timing) is covered by later U2-U4 fixtures; the state contract proven
here is the foundation they consume.
"""
from datetime import date

import pytest

from retirement_planner.household import (
    SurvivorSnapshot,
    active_dependent_count,
    configured_death_year,
    normalize_filing_status,
    survivor_snapshot,
)
from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import (
    Account,
    Dependent,
    EconomicAssumptions,
    Expense,
    Person,
    Scenario,
    SocialSecurity,
)
from retirement_planner.tax_law import FilingStatus


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------
def make_person(name, birth_year, longevity, retirement_year=2025):
    return Person(
        name=name,
        birth_date=date(birth_year, 1, 1),
        retirement_date=date(retirement_year, 1, 1),
        longevity_age=longevity,
    )


def make_dependent(birth_year, name="Child"):
    return Dependent(birth_date=date(birth_year, 1, 1), name=name)


# Primary dies first: primary 1960/80 -> 2040, spouse 1962/90 -> 2052.
PRIMARY_FIRST = (
    make_person("Primary", 1960, 80),
    make_person("Spouse", 1962, 90),
)

# Spouse dies first: spouse 1960/80 -> 2040, primary 1962/90 -> 2052.
SPOUSE_FIRST = (
    make_person("Primary", 1962, 90),
    make_person("Spouse", 1960, 80),
)

# Equal death years: both 1960/80 -> 2040.
EQUAL = (
    make_person("Primary", 1960, 80),
    make_person("Spouse", 1960, 80),
)


# ---------------------------------------------------------------------------
# Death-year derivation (R1)
# ---------------------------------------------------------------------------
class TestDeathYearDerivation:
    def test_configured_death_year(self):
        p = make_person("P", 1960, 80)
        assert configured_death_year(p) == 2040

    def test_death_year_is_final_full_year(self):
        # alive during death year, dead the year after
        p, s = PRIMARY_FIRST
        dy = configured_death_year(p)
        snap_alive = survivor_snapshot(dy, p, s)
        snap_dead = survivor_snapshot(dy + 1, p, s)
        assert snap_alive.primary_alive is True
        assert snap_dead.primary_alive is False


# ---------------------------------------------------------------------------
# Both alive
# ---------------------------------------------------------------------------
class TestBothAlive:
    def test_mfj_and_no_survivor(self):
        p, s = PRIMARY_FIRST
        snap = survivor_snapshot(2030, p, s)
        assert snap.primary_alive and snap.spouse_alive
        assert snap.filing_status is FilingStatus.MFJ
        assert snap.survivor is None
        assert snap.estate_event is False
        assert snap.is_first_death_year is False
        assert snap.is_second_death_year is False


# ---------------------------------------------------------------------------
# Primary dies first (AE1)
# ---------------------------------------------------------------------------
class TestPrimaryFirst:
    def test_death_year_is_mfj(self):
        p, s = PRIMARY_FIRST
        snap = survivor_snapshot(2040, p, s)
        assert snap.primary_alive and snap.spouse_alive
        assert snap.is_primary_death_year is True
        assert snap.is_first_death_year is True
        assert snap.filing_status is FilingStatus.MFJ

    def test_post_death_single_no_dependents(self):
        p, s = PRIMARY_FIRST
        snap = survivor_snapshot(2041, p, s)
        assert snap.primary_alive is False
        assert snap.spouse_alive is True
        assert snap.survivor == "spouse"
        # No dependents -> Single after the death year (R3).
        assert snap.filing_status is FilingStatus.SINGLE

    def test_second_death_estate_event(self):
        p, s = PRIMARY_FIRST
        snap = survivor_snapshot(2052, p, s)
        assert snap.is_spouse_death_year is True
        assert snap.is_second_death_year is True
        assert snap.estate_event is True
        assert snap.survivor == "spouse"


# ---------------------------------------------------------------------------
# Spouse dies first (AE2) — symmetry
# ---------------------------------------------------------------------------
class TestSpouseFirst:
    def test_death_year_is_mfj(self):
        p, s = SPOUSE_FIRST
        snap = survivor_snapshot(2040, p, s)
        assert snap.primary_alive and snap.spouse_alive
        assert snap.is_spouse_death_year is True
        assert snap.is_first_death_year is True
        assert snap.filing_status is FilingStatus.MFJ

    def test_post_death_single_no_dependents(self):
        p, s = SPOUSE_FIRST
        snap = survivor_snapshot(2041, p, s)
        assert snap.spouse_alive is False
        assert snap.primary_alive is True
        assert snap.survivor == "primary"
        assert snap.filing_status is FilingStatus.SINGLE

    def test_second_death_estate_event(self):
        p, s = SPOUSE_FIRST
        snap = survivor_snapshot(2052, p, s)
        assert snap.is_primary_death_year is True
        assert snap.is_second_death_year is True
        assert snap.estate_event is True
        assert snap.survivor == "primary"


# ---------------------------------------------------------------------------
# Dependents -> QSS then HOH (AE3, R3)
# ---------------------------------------------------------------------------
class TestDependentFilingPhases:
    def test_qss_years_1_and_2_then_hoh(self):
        p, s = PRIMARY_FIRST
        dep = make_dependent(2030)  # age 11/12 in 2041/2042, <26
        # Year 1 after primary death (2041): QSS
        assert survivor_snapshot(2041, p, s, [dep]).filing_status is FilingStatus.QSS
        # Year 2 after primary death (2042): QSS
        assert survivor_snapshot(2042, p, s, [dep]).filing_status is FilingStatus.QSS
        # Year 3+ (2043): HOH while dependents remain
        assert survivor_snapshot(2043, p, s, [dep]).filing_status is FilingStatus.HOH
        # Without dependents: Single
        assert survivor_snapshot(2043, p, s, []).filing_status is FilingStatus.SINGLE

    def test_no_dependent_post_death_single(self):
        p, s = PRIMARY_FIRST
        snap = survivor_snapshot(2045, p, s, [])
        assert snap.filing_status is FilingStatus.SINGLE


# ---------------------------------------------------------------------------
# Equal death years -> combined/MFJ estate (R8)
# ---------------------------------------------------------------------------
class TestEqualDeaths:
    def test_equal_year_mfj_estate(self):
        p, s = EQUAL
        snap = survivor_snapshot(2040, p, s)
        assert snap.primary_alive and snap.spouse_alive
        assert snap.is_first_death_year is False
        assert snap.is_second_death_year is True
        assert snap.estate_event is True
        assert snap.filing_status is FilingStatus.MFJ

    def test_post_equal_no_years(self):
        p, s = EQUAL
        snap = survivor_snapshot(2041, p, s)
        assert snap.primary_alive is False
        assert snap.spouse_alive is False
        assert snap.survivor is None
        assert snap.estate_event is False


# ---------------------------------------------------------------------------
# Coverage counts (R5) — separate ACA family size and Medicare adult count
# ---------------------------------------------------------------------------
class TestCoverageCounts:
    # Younger couple so ACA-eligible (under-65) adults exist in 2030.
    YOUNG = (
        make_person("Primary", 1990, 90),  # death 2080
        make_person("Spouse", 1992, 90),   # death 2082
    )

    def test_aca_family_size_under_65_plus_dependents(self):
        p, s = self.YOUNG
        dep_young = make_dependent(2028)  # age 2 in 2030, ages out by 2054
        # 2030: ages 40/38 (<65, ACA) + dependent age 2 (<26) -> 3
        assert survivor_snapshot(2030, p, s, [dep_young]).aca_family_size == 3
        # 2070: both 80/78 (>=65) and dependent age 42 (>26) -> 0
        assert survivor_snapshot(2070, p, s, [dep_young]).aca_family_size == 0
        dep_late = make_dependent(2068)  # age 2 in 2070, 13 in 2081
        # 2070: both >=65; dependent age 2 (<26) remains ACA-eligible -> 1
        assert survivor_snapshot(2070, p, s, [dep_late]).aca_family_size == 1
        # 2081: primary dead, spouse Medicare-aged; dependent age 13 -> 1
        assert survivor_snapshot(2081, p, s, [dep_late]).aca_family_size == 1

    def test_medicare_adult_count_only_eligible(self):
        p, s = self.YOUNG
        # 2030: both 40/38 (<65) -> 0 Medicare-eligible
        assert survivor_snapshot(2030, p, s).medicare_adult_count == 0
        # 2070: both 80/78 (>=65) -> 2 Medicare-eligible
        assert survivor_snapshot(2070, p, s).medicare_adult_count == 2
        # 2081: primary dead, spouse 89 (>=65) -> 1 Medicare-eligible
        assert survivor_snapshot(2081, p, s).medicare_adult_count == 1


# ---------------------------------------------------------------------------
# Filing-status normalization (KTD8)
# ---------------------------------------------------------------------------
class TestNormalizeFilingStatus:
    @pytest.mark.parametrize("raw,expected", [
        ("MFJ", FilingStatus.MFJ),
        ("mfj", FilingStatus.MFJ),
        ("QSS", FilingStatus.QSS),
        ("hoh", FilingStatus.HOH),
        ("SINGLE", FilingStatus.SINGLE),
        (FilingStatus.HOH, FilingStatus.HOH),
    ])
    def test_normalizes(self, raw, expected):
        assert normalize_filing_status(raw) is expected


# ---------------------------------------------------------------------------
# Snapshot type contract
# ---------------------------------------------------------------------------
class TestSnapshotContract:
    def test_is_survivor_snapshot(self):
        p, s = PRIMARY_FIRST
        assert isinstance(survivor_snapshot(2030, p, s), SurvivorSnapshot)

    def test_active_dependent_count_cutoff(self):
        dep = make_dependent(2000)  # old -> not a dependent
        assert active_dependent_count(2030, [dep]) == 0
        dep2 = make_dependent(2030)
        assert active_dependent_count(2030, [dep2]) == 1


# ---------------------------------------------------------------------------
# Engine integration: survivor Social Security (R4) and expense scaling (R6)
# ---------------------------------------------------------------------------
def _build(primary_birth, spouse_birth, primary_lon, spouse_lon,
           ss=(1000, 800), expense_monthly=0.0, ratio=0.75,
           balance=10_000_000):
    scenario = Scenario(
        name="surv", description="", state="CA",
        primary=Person("P", date(primary_birth, 1, 1), date(2025, 1, 1), primary_lon),
        spouse=Person("S", date(spouse_birth, 1, 1), date(2025, 1, 1), spouse_lon),
        economic=EconomicAssumptions(),
        accounts=[Account("b", "B", "brokerage", "taxable", balance, growth_rate=0.0)],
        income_streams=[],
        expenses=([Expense("l", "L", expense_monthly, date(2025, 1, 1),
                           date(2100, 1, 1), is_must_spend=True)]
                   if expense_monthly > 0 else []),
        mortgages=[],
        social_security=SocialSecurity(
            primary_benefit_at_67=ss[0], spouse_benefit_at_67=ss[1],
            primary_claiming_age=67, spouse_claiming_age=67),
        survivor_expense_ratio=ratio,
    )
    return RetirementPlanner(scenario)


class TestSurvivorSocialSecurity:
    # Primary dies first: 1990/80 -> 2070; spouse 1992/90 -> 2082.
    def test_primary_first_retains_then_selects(self):
        pl = _build(1990, 1992, 80, 90, ss=(1000, 800))
        proj = {r["year"]: r for r in pl.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        # Both alive and claiming (2065): both payable benefits retained.
        assert proj[2065]["primary_alive"] and proj[2065]["spouse_alive"]
        ss_p = pl.calculate_social_security(2065, pl.scenario.primary)
        ss_s = pl.calculate_social_security(2065, pl.scenario.spouse)
        assert proj[2065]["income"] == pytest.approx(ss_p + ss_s)
        # Death year (2070): still both alive -> both benefits retained.
        ss_p_d = pl.calculate_social_security(2070, pl.scenario.primary)
        ss_s_d = pl.calculate_social_security(2070, pl.scenario.spouse)
        assert proj[2070]["income"] == pytest.approx(ss_p_d + ss_s_d)
        # Year after primary death (2071): survivor gets higher payable.
        assert proj[2071]["primary_alive"] is False
        assert proj[2071]["survivor"] == "spouse"
        ss_p_a = pl.calculate_social_security(2071, pl.scenario.primary)
        ss_s_a = pl.calculate_social_security(2071, pl.scenario.spouse)
        assert proj[2071]["income"] == pytest.approx(max(ss_p_a, ss_s_a))
        assert proj[2071]["income"] < proj[2070]["income"]

    def test_spouse_first_retains_then_selects(self):
        pl = _build(1992, 1990, 90, 80, ss=(1000, 800))
        proj = {r["year"]: r for r in pl.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        ss_p = pl.calculate_social_security(2065, pl.scenario.primary)
        ss_s = pl.calculate_social_security(2065, pl.scenario.spouse)
        assert proj[2065]["income"] == pytest.approx(ss_p + ss_s)
        # Spouse dies first (2070); year after, survivor (primary) gets max.
        assert proj[2071]["spouse_alive"] is False
        assert proj[2071]["survivor"] == "primary"
        ss_p_a = pl.calculate_social_security(2071, pl.scenario.primary)
        ss_s_a = pl.calculate_social_security(2071, pl.scenario.spouse)
        assert proj[2071]["income"] == pytest.approx(max(ss_p_a, ss_s_a))

    def test_unclaimed_deceased_benefit_absent(self):
        # Primary dies before claiming age (65 < 67) -> no payable benefit,
        # so the survivor receives only the spouse's benefit (R4).  Spouse
        # also pre-claiming here, so income is zero until they claim.
        pl = _build(1990, 1992, 65, 90, ss=(1000, 800))
        proj = {r["year"]: r for r in pl.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        row = proj[2056]  # primary dead (age 65), spouse age 63 (<67)
        assert row["primary_alive"] is False
        assert row["income"] == pytest.approx(0.0)


class TestSurvivorExpenseRatio:
    def test_scales_post_death(self):
        base = _build(1990, 1992, 80, 90, expense_monthly=2000, ratio=1.0)
        scaled = _build(1990, 1992, 80, 90, expense_monthly=2000, ratio=0.75)
        b = {r["year"]: r for r in base.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        s = {r["year"]: r for r in scaled.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        # Pre-death (both alive): identical expenses.
        assert b[2069]["expenses"] == pytest.approx(s[2069]["expenses"])
        # Post-primary-death (2071): scaled = 0.75 * base (same-year med/
        # IRMAA terms, so the only difference is the ratio).
        assert s[2071]["expenses"] == pytest.approx(
            b[2071]["expenses"] * 0.75, rel=1e-9)
        assert s[2071]["expense_ratio"] == 0.75

    def test_custom_ratio(self):
        base = _build(1990, 1992, 80, 90, expense_monthly=2000, ratio=1.0)
        scaled = _build(1990, 1992, 80, 90, expense_monthly=2000, ratio=0.5)
        b = {r["year"]: r for r in base.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        s = {r["year"]: r for r in scaled.run_single_simulation(
            return_volatility=0.0, collect_projections=True)["projections"]}
        assert s[2071]["expenses"] == pytest.approx(
            b[2071]["expenses"] * 0.5, rel=1e-9)
        assert s[2071]["expense_ratio"] == 0.5
