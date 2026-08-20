"""U4: MC ↔ deterministic survivor parity.

Both projection paths consume the same ``survivor_snapshot()`` (KTD1/R9),
so alive flags, filing status, survivor identity, ACA/Medicare counts,
expense ratio, and estate tax timing must agree year-by-year.

Scope of the guarantee (matching the existing parity harness convention):
- Survivor state fields agree in EVERY config (derived from the same
  longevity ages and dependents).
- Financial fields (income, taxes, net_worth) are NOT parity targets
  here — MC includes withdrawals/contributions that deterministic omits
  by design.  They are already covered by test_mc_deterministic_parity.py.
- Estate tax timing (which year fires) matches; the monetary amount may
  diverge because MC includes withdrawals/contributions that change the
  net-worth base.
"""
from datetime import date

import pytest

from retirement_planner import RetirementPlanner
from retirement_planner.models import (
    Account, Dependent, EconomicAssumptions, Expense,
    IncomeStream, MonetaryConvention, Person, Scenario,
    SocialSecurity,
)

# Survivor state fields that must match across MC and deterministic.
SURVIVOR_KEYS = (
    "primary_alive", "spouse_alive", "filing_status",
    "survivor", "aca_family_size", "medicare_adult_count",
    "expense_ratio",
)


# ---------------------------------------------------------------------------
# Helpers
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


def _build(
    primary_birth, spouse_birth, primary_lon, spouse_lon,
    dependents=None,
    real=True,
    ss_benefits=(2100, 1500),
    balance=10_000_000,
    ratio=0.75,
):
    """Build a parity-focused scenario with asymmetric longevity."""
    scenario = Scenario(
        name="parity_survivor", description="", state="CA",
        primary=make_person("P", primary_birth, primary_lon),
        spouse=make_person("S", spouse_birth, spouse_lon),
        economic=EconomicAssumptions(),
        accounts=[
            Account("b", "B", "brokerage", "taxable", balance,
                    growth_rate=0.0, equity_pct=0.6),
        ],
        income_streams=[],
        expenses=[],
        mortgages=[],
        social_security=SocialSecurity(
            primary_benefit_at_67=ss_benefits[0],
            spouse_benefit_at_67=ss_benefits[1],
            primary_claiming_age=67, spouse_claiming_age=67,
        ),
        dependents=dependents or [],
        survivor_expense_ratio=ratio,
        monetary_convention=(
            MonetaryConvention.REAL if real else MonetaryConvention.NOMINAL),
    )
    return RetirementPlanner(scenario)


def both_paths(planner):
    """Run deterministic and MC (zero-volatility) and return year-keyed rows."""
    det = {r["year"]: r for r in planner.project_cash_flow()}
    mc = {r["year"]: r for r in planner.run_single_simulation(
        return_volatility=0.0, collect_projections=True)["projections"]}
    return det, mc


def assert_survivor_parity(det, mc, keys=SURVIVOR_KEYS, label=""):
    """Assert survivor state fields match across paths for every year."""
    assert set(det.keys()) == set(mc.keys()), (
        f"{label}: horizon mismatch det={sorted(det)} mc={sorted(mc)}")
    for year in sorted(det):
        for key in keys:
            d = det[year][key]
            m = mc[year][key]
            assert d == m, (
                f"{label}: {key} diverged in {year}: det={d!r} mc={m!r}")


# ---------------------------------------------------------------------------
# Configs: asymmetric longevity, both death orders
# ---------------------------------------------------------------------------
# Primary dies first: P 1960/80 -> 2040, S 1962/90 -> 2052
PRIMARY_FIRST = (1960, 1962, 80, 90)
# Spouse dies first: P 1962/90 -> 2052, S 1960/80 -> 2040
SPOUSE_FIRST = (1962, 1960, 90, 80)


class TestSurvivorFieldParity:
    """Survivor state fields match across MC and deterministic paths."""

    @pytest.mark.parametrize("label,args,real", [
        ("REAL primary-first", PRIMARY_FIRST, True),
        ("REAL spouse-first", SPOUSE_FIRST, True),
        ("NOMINAL primary-first", PRIMARY_FIRST, False),
        ("NOMINAL spouse-first", SPOUSE_FIRST, False),
    ])
    def test_survivor_fields_match(self, label, args, real):
        p = _build(*args, real=real)
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, label=label)

    def test_filing_status_transitions_primary_first(self):
        """mfj -> qss -> hoh/single with a dependent."""
        dep = make_dependent(2030)
        p = _build(1960, 1962, 80, 90, dependents=[dep])
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("filing_status",),
                               label="filing-status-primary-first")
        # Verify the expected transition sequence (FilingStatus values are lowercase)
        assert det[2039]["filing_status"] == "mfj"   # both alive
        assert det[2040]["filing_status"] == "mfj"   # death year, still mfj
        assert det[2041]["filing_status"] == "qss"   # year 1 after death
        assert det[2042]["filing_status"] == "qss"   # year 2 after death
        assert det[2043]["filing_status"] == "hoh"   # year 3+, dependents remain
        # Verify parity agrees on every transition year
        for year in [2040, 2041, 2042, 2043, 2050]:
            assert det[year]["filing_status"] == mc[year]["filing_status"]

    def test_filing_status_transitions_spouse_first(self):
        """Same transitions with reversed death order."""
        dep = make_dependent(2030)
        p = _build(1962, 1960, 90, 80, dependents=[dep])
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("filing_status",),
                               label="filing-status-spouse-first")
        assert det[2039]["filing_status"] == "mfj"
        assert det[2040]["filing_status"] == "mfj"
        assert det[2041]["filing_status"] == "qss"
        assert det[2042]["filing_status"] == "qss"
        assert det[2043]["filing_status"] == "hoh"

    def test_no_dependent_post_death_single(self):
        """Without dependents, post-death status is single."""
        p = _build(1960, 1962, 80, 90, dependents=[])
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("filing_status",),
                               label="single-no-dep")
        assert det[2041]["filing_status"] == "single"
        assert mc[2041]["filing_status"] == "single"


class TestACAMedicareParity:
    """ACA family size and Medicare adult count match across paths.

    Note: ACA covers people under 65; Medicare covers 65+.
    With primary born 1960 and spouse born 1962, both are >=65 from 2025
    onward, so ACA-eligible adults = 0.  Dependents under 26 still count
    toward ACA family size.
    """

    def test_aca_family_size_with_young_dependent(self):
        """Young dependent (born 2030) is ACA-eligible through 2055."""
        dep = make_dependent(2030)
        p = _build(1960, 1962, 80, 90, dependents=[dep])
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("aca_family_size",),
                               label="aca-family")
        # 2039: both adults >=65 (Medicare), dependent age 9 (<26) -> 1
        assert det[2039]["aca_family_size"] == 1
        # 2041: primary dead, spouse alive (>=65), dep age 11 -> 1
        assert det[2041]["aca_family_size"] == 1
        # 2052: spouse death year (still alive), dep age 22 -> 1
        assert det[2052]["aca_family_size"] == 1

    def test_aca_family_size_with_young_adults(self):
        """Younger couple (born 1990/1992): ACA-eligible adults + dependents."""
        dep = make_dependent(2028)
        p = _build(1990, 1992, 90, 90, dependents=[dep])
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("aca_family_size",),
                               label="aca-family-young")
        # 2030: ages 40/38 (<65, ACA) + dep age 2 -> 3
        assert det[2030]["aca_family_size"] == 3
        # 2070: both 80/78 (>=65, Medicare) -> 0
        assert det[2070]["aca_family_size"] == 0

    def test_medicare_count_decreases_at_death(self):
        """After first death, Medicare covered-adult count drops by 1."""
        p = _build(1960, 1962, 80, 90)
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("medicare_adult_count",),
                               label="medicare-count")
        # 2039: both age 79/77 (>=65) -> 2
        assert det[2039]["medicare_adult_count"] == 2
        # 2041: primary dead, spouse age 79 -> 1
        assert det[2041]["medicare_adult_count"] == 1
        # 2052: spouse death year (still alive), age 90 -> 1
        assert det[2052]["medicare_adult_count"] == 1

    def test_medicare_count_young_couple(self):
        """Younger couple: no Medicare until age 65."""
        p = _build(1990, 1992, 90, 90)
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("medicare_adult_count",),
                               label="medicare-young")
        # 2050: ages 60/58 (<65) -> 0
        assert det[2050]["medicare_adult_count"] == 0
        # 2056: ages 66/64 -> primary eligible, spouse not -> 1
        assert det[2056]["medicare_adult_count"] == 1
        # 2058: ages 68/66 -> both eligible -> 2
        assert det[2058]["medicare_adult_count"] == 2


class TestExpenseRatioParity:
    """Survivor expense ratio applies identically in both paths."""

    def test_ratio_applies_post_death(self):
        p = _build(1960, 1962, 80, 90, ratio=0.75)
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("expense_ratio",),
                               label="expense-ratio")
        # Both alive: ratio = 1.0
        assert det[2039]["expense_ratio"] == 1.0
        # After first death: ratio = 0.75
        assert det[2041]["expense_ratio"] == 0.75

    def test_ratio_1_0_no_scaling(self):
        p = _build(1960, 1962, 80, 90, ratio=1.0)
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("expense_ratio",),
                               label="ratio-1.0")
        assert det[2041]["expense_ratio"] == 1.0


class TestEstateTaxTimingParity:
    """Estate tax fires at second death in both paths.

    The monetary amount may diverge because MC includes withdrawals and
    contributions that change the net-worth base.  We test timing
    (which year fires) and the zero-before-second-death invariant.
    """

    def test_estate_timing_primary_first(self):
        p = _build(1960, 1962, 80, 90, balance=50_000_000)
        det, mc = both_paths(p)
        # First death: no estate tax in either path
        assert det[2040]["estate_tax"] == 0.0
        assert mc[2040]["estate_tax"] == 0.0
        # Second death: estate tax fires in both
        assert det[2052]["estate_tax"] > 0.0
        assert mc[2052]["estate_tax"] > 0.0
        # Exactly one year with estate tax
        det_estate_years = [y for y, r in det.items() if r["estate_tax"] > 0]
        mc_estate_years = [y for y, r in mc.items() if r["estate_tax"] > 0]
        assert det_estate_years == mc_estate_years == [2052]

    def test_estate_timing_spouse_first(self):
        p = _build(1962, 1960, 90, 80, balance=50_000_000)
        det, mc = both_paths(p)
        assert det[2040]["estate_tax"] == 0.0
        assert det[2052]["estate_tax"] > 0.0
        det_estate_years = [y for y, r in det.items() if r["estate_tax"] > 0]
        mc_estate_years = [y for y, r in mc.items() if r["estate_tax"] > 0]
        assert det_estate_years == mc_estate_years == [2052]

    def test_estate_timing_equal_deaths(self):
        p = _build(1960, 1960, 80, 80, balance=50_000_000)
        det, mc = both_paths(p)
        # Equal death year: estate fires once at 2040
        assert det[2040]["estate_tax"] > 0.0
        assert mc[2040]["estate_tax"] > 0.0
        det_estate_years = [y for y, r in det.items() if r["estate_tax"] > 0]
        mc_estate_years = [y for y, r in mc.items() if r["estate_tax"] > 0]
        assert det_estate_years == mc_estate_years == [2040]


class TestHorizonParity:
    """Both paths run to the same final year."""

    def test_horizons_match_primary_first(self):
        p = _build(1960, 1962, 80, 90)
        det, mc = both_paths(p)
        assert set(det.keys()) == set(mc.keys())
        # Last year = max(primary_death, spouse_death) = 2052
        assert max(det.keys()) == 2052

    def test_horizons_match_spouse_first(self):
        p = _build(1962, 1960, 90, 80)
        det, mc = both_paths(p)
        assert set(det.keys()) == set(mc.keys())
        assert max(det.keys()) == 2052

    def test_horizons_match_equal_deaths(self):
        p = _build(1960, 1960, 80, 80)
        det, mc = both_paths(p)
        assert set(det.keys()) == set(mc.keys())
        assert max(det.keys()) == 2040


class TestAliveFlagsParity:
    """Alive flags are the most basic survivor state — must match exactly."""

    def test_both_death_orders(self):
        for label, args in [("primary-first", PRIMARY_FIRST),
                            ("spouse-first", SPOUSE_FIRST)]:
            p = _build(*args)
            det, mc = both_paths(p)
            assert_survivor_parity(det, mc,
                                   keys=("primary_alive", "spouse_alive"),
                                   label=label)

    def test_survivor_identity_matches_alive_flags(self):
        """survivor field is consistent with alive flags."""
        p = _build(*PRIMARY_FIRST)
        det, mc = both_paths(p)
        assert_survivor_parity(det, mc, keys=("survivor",),
                               label="survivor-identity")
        # Verify survivor identity is consistent with alive flags
        for year in sorted(det):
            d = det[year]
            if d["primary_alive"] and d["spouse_alive"]:
                assert d["survivor"] is None
            elif d["primary_alive"]:
                assert d["survivor"] == "primary"
            elif d["spouse_alive"]:
                assert d["survivor"] == "spouse"
            else:
                assert d["survivor"] is None
