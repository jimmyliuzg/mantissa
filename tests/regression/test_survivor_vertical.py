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
from retirement_planner.models import Dependent, Person
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
    def test_aca_family_size_includes_dependents(self):
        p, s = PRIMARY_FIRST
        dep = make_dependent(2030)
        snap_alive = survivor_snapshot(2030, p, s, [dep])
        assert snap_alive.aca_family_size == 3  # 2 adults + 1 dependent

        snap_widowed = survivor_snapshot(2041, p, s, [dep])
        # One adult (spouse) + 1 dependent
        assert snap_widowed.aca_family_size == 2

    def test_medicare_adult_count_only_eligible(self):
        p, s = PRIMARY_FIRST
        # In 2030 both are 68/70 -> both Medicare-eligible
        snap = survivor_snapshot(2030, p, s)
        assert snap.medicare_adult_count == 2
        # In 2041 primary (81) dead, spouse (79) Medicare-eligible
        snap2 = survivor_snapshot(2041, p, s)
        assert snap2.medicare_adult_count == 1


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
