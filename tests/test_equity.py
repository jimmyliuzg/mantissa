"""Tests for RSU vesting math (engine.py equity compensation methods)."""
from datetime import date
import pytest

from retirement_planner.models import (
    RSUGrant, RefresherPolicy, EquityComp, IncomeStream, Person,
    Scenario, EconomicAssumptions,
)
from retirement_planner.engine import RetirementPlanner


# ---------------------------------------------------------------------------
# Fixture: minimal planner with no accounts (just need vesting methods)
# ---------------------------------------------------------------------------
def _make_planner():
    primary = Person(name="Jimmy", birth_date=date(1990, 1, 1),
                     retirement_date=date(2035, 1, 1), longevity_age=90)
    spouse = Person(name="Faith", birth_date=date(1991, 1, 1),
                    retirement_date=date(2036, 1, 1), longevity_age=90)
    scenario = Scenario(
        name="Test", description="",
        primary=primary, spouse=spouse,
        economic=EconomicAssumptions(),
        accounts=[], income_streams=[], expenses=[], mortgages=[],
    )
    return RetirementPlanner(scenario)


@pytest.fixture
def planner():
    return _make_planner()


# ---------------------------------------------------------------------------
# Grant 1: Faith's cliff + quarterly (cliff on top, no replaces)
# ---------------------------------------------------------------------------
class TestGrant1CliffQuarterly:
    """Grant 1: 3,951 total shares, cliff 1,975 at Oct 2026, quarterly 494 after."""

    @pytest.fixture
    def grant1(self):
        return RSUGrant(
            id="grant_1_2025",
            grant_date=date(2025, 10, 10),
            total_shares=3951,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1975,
            periodic_shares=494,
            cliff_date=date(2026, 10, 10),
            cliff_replaces_first_vest=False,
        )

    def test_2025_grant_year(self, planner, grant1):
        """2025: no vest before cliff."""
        assert planner._cliff_quarterly_vests(grant1, 2025) == 0

    def test_2026_cliff_year(self, planner, grant1):
        """2026: cliff only (1,975)."""
        assert planner._cliff_quarterly_vests(grant1, 2026) == 1975

    def test_2027_post_cliff(self, planner, grant1):
        """2027: quarterly only (494×4 = 1,976)."""
        assert planner._cliff_quarterly_vests(grant1, 2027) == 1976

    def test_2028_beyond_vest(self, planner, grant1):
        """2028: all shares already vested."""
        assert planner._cliff_quarterly_vests(grant1, 2028) == 0

    def test_total_vested(self, planner, grant1):
        """Full vest: 1,975 + 1,976 = 3,951."""
        total = sum(planner._cliff_quarterly_vests(grant1, y) for y in range(2025, 2030))
        assert total == 3951


# ---------------------------------------------------------------------------
# Grant 2: Faith's quarterly-only (no cliff)
# ---------------------------------------------------------------------------
class TestGrant2Quarterly:
    """Grant 2: 230 total shares, quarterly 57."""

    @pytest.fixture
    def grant2(self):
        return RSUGrant(
            id="grant_2_2025",
            grant_date=date(2025, 8, 10),
            total_shares=230,
            vesting_pattern="quarterly",
            periodic_shares=57,
        )

    def test_2025_grant_year(self, planner, grant2):
        """2025: Aug-Dec = 5 months, 5//3=1 quarter → 57 shares."""
        assert planner._quarterly_vests(grant2, 2025) == 57

    def test_2026_full_year(self, planner, grant2):
        """2026: 230 total - 57 already vested = 173 remaining."""
        assert planner._quarterly_vests(grant2, 2026) == 173

    def test_2027_beyond_vest(self, planner, grant2):
        """2027: all 230 shares already vested."""
        assert planner._quarterly_vests(grant2, 2027) == 0

    def test_total_vested(self, planner, grant2):
        """Full vest: 57 + 173 = 230."""
        total = sum(planner._quarterly_vests(grant2, y) for y in range(2025, 2030))
        assert total == 230


# ---------------------------------------------------------------------------
# cliff_replaces_first_vest=True
# ---------------------------------------------------------------------------
class TestCliffReplacesFirstVest:

    @pytest.fixture
    def grant_replaces(self):
        return RSUGrant(
            id="grant_replaces",
            grant_date=date(2025, 10, 10),
            total_shares=3951,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1975,
            periodic_shares=494,
            cliff_date=date(2026, 10, 10),
            cliff_replaces_first_vest=True,
        )

    def test_cliff_year_with_replacement(self, planner, grant_replaces):
        """Cliff year: cliff (1,975) + 3 quarterly (494×3=1,482) = 3,457."""
        assert planner._cliff_quarterly_vests(grant_replaces, 2026) == 1975 + 494 * 3

    def test_post_cliff_year(self, planner, grant_replaces):
        """After cliff: 1 quarterly remaining (494×4=1,976 minus 3 already = 494)."""
        assert planner._cliff_quarterly_vests(grant_replaces, 2027) == 494

    def test_total_vested(self, planner, grant_replaces):
        """Full vest: 3,457 + 494 = 3,951."""
        total = sum(planner._cliff_quarterly_vests(grant_replaces, y) for y in range(2025, 2030))
        assert total == 3951


# ---------------------------------------------------------------------------
# Monthly vesting
# ---------------------------------------------------------------------------
class TestMonthlyVesting:

    @pytest.fixture
    def grant_monthly(self):
        return RSUGrant(
            id="grant_monthly",
            grant_date=date(2026, 3, 1),
            total_shares=1200,
            vesting_pattern="monthly",
            periodic_shares=25,
        )

    def test_grant_year_partial(self, planner, grant_monthly):
        """2026: Mar-Dec = 10 months → 25×10 = 250."""
        assert planner._monthly_vests(grant_monthly, 2026) == 250

    def test_full_year(self, planner, grant_monthly):
        """2027: full year → 25×12 = 300."""
        assert planner._monthly_vests(grant_monthly, 2027) == 300

    def test_beyond_vest(self, planner, grant_monthly):
        """2030: only 2 months remaining (48-46=2) → 50."""
        assert planner._monthly_vests(grant_monthly, 2030) == 50

    def test_total_vested(self, planner, grant_monthly):
        """Full vest: cap at 48 months → 25×48 = 1,200."""
        total = sum(planner._monthly_vests(grant_monthly, y) for y in range(2026, 2031))
        assert total == 1200


# ---------------------------------------------------------------------------
# End date (job termination) stops vests
# ---------------------------------------------------------------------------
class TestEndDate:

    @pytest.fixture
    def grant(self):
        return RSUGrant(
            id="grant_1",
            grant_date=date(2025, 10, 10),
            total_shares=3951,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1975,
            periodic_shares=494,
            cliff_date=date(2026, 10, 10),
        )

    def test_end_date_before_grant(self, planner, grant):
        """Grant created after end_date → skipped entirely."""
        equity = EquityComp(
            ticker="DOCU", current_price=55.59,
            grants=[grant],
            end_date=date(2025, 6, 1),  # before grant
        )
        assert planner.calculate_annual_rsu_income(2026, equity) == 0

    def test_end_date_mid_year(self, planner, grant):
        """Job ends mid-year → no vests after end_date."""
        equity = EquityComp(
            ticker="DOCU", current_price=55.59,
            grants=[grant],
            end_date=date(2026, 6, 1),  # before cliff
        )
        assert planner.calculate_annual_rsu_income(2026, equity) == 0


# ---------------------------------------------------------------------------
# RefresherPolicy auto-generation
# ---------------------------------------------------------------------------
class TestRefresherPolicy:

    def test_basic_refresher(self, planner):
        """Single refresher grant generates vests in subsequent years."""
        equity = EquityComp(
            ticker="DOCU", current_price=55.59,
            grants=[],
            refreshers=RefresherPolicy(
                annual_shares=494,
                grant_month=10,
                vesting_pattern="quarterly",
                start_year=2026,
                end_year=2035,
                growth_rate=0.0,
            ),
        )
        # 2026: refresher granted Oct → 1 quarter (123.5 shares)
        inc_2026 = planner.calculate_annual_rsu_income(2026, equity)
        assert inc_2026 == pytest.approx(123.5 * 55.59, rel=1e-3)

        # 2027: Grant 2026 full year (494) + Grant 2027 partial (123.5) = 617.5
        inc_2027 = planner.calculate_annual_rsu_income(2027, equity)
        assert inc_2027 == pytest.approx(617.5 * 55.59, rel=1e-3)

    def test_compounding_refreshers(self, planner):
        """Multiple years of refreshers compound."""
        equity = EquityComp(
            ticker="DOCU", current_price=55.59,
            grants=[],
            refreshers=RefresherPolicy(
                annual_shares=494,
                grant_month=10,
                vesting_pattern="quarterly",
                start_year=2026,
                end_year=2035,
                growth_rate=0.0,
            ),
        )
        # 2028: Grant 2026 (494) + Grant 2027 (494) + Grant 2028 (123.5) = 1,111.5
        inc_2028 = planner.calculate_annual_rsu_income(2028, equity)
        assert inc_2028 == pytest.approx(1111.5 * 55.59, rel=1e-3)

    def test_refresher_with_growth(self, planner):
        """Refresher with 5% annual growth in grant size."""
        equity = EquityComp(
            ticker="DOCU", current_price=55.59,
            grants=[],
            refreshers=RefresherPolicy(
                annual_shares=494,
                grant_month=10,
                vesting_pattern="quarterly",
                start_year=2026,
                end_year=2035,
                growth_rate=0.05,
            ),
        )
        # 2027: Grant 2026 (494) + Grant 2027 (494×1.05=518.7, 1 quarter=129.675)
        inc_2027 = planner.calculate_annual_rsu_income(2027, equity)
        expected_shares = 494 + 518.7 / 4  # 494 + 129.675
        assert inc_2027 == pytest.approx(expected_shares * 55.59, rel=1e-3)


# ---------------------------------------------------------------------------
# Price sensitivity
# ---------------------------------------------------------------------------
class TestPriceSensitivity:

    def test_different_prices(self, planner):
        """Same shares, different DOCU price → different income."""
        grant = RSUGrant(
            id="grant_1",
            grant_date=date(2025, 10, 10),
            total_shares=3951,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1975,
            periodic_shares=494,
            cliff_date=date(2026, 10, 10),
        )

        equity_low = EquityComp(ticker="DOCU", current_price=38.0, grants=[grant])
        equity_mid = EquityComp(ticker="DOCU", current_price=55.59, grants=[grant])
        equity_high = EquityComp(ticker="DOCU", current_price=72.0, grants=[grant])

        shares_2026 = planner._cliff_quarterly_vests(grant, 2026)

        assert planner.calculate_annual_rsu_income(2026, equity_low) == shares_2026 * 38.0
        assert planner.calculate_annual_rsu_income(2026, equity_mid) == shares_2026 * 55.59
        assert planner.calculate_annual_rsu_income(2026, equity_high) == shares_2026 * 72.0


# ---------------------------------------------------------------------------
# Combined: Grant 1 + Grant 2
# ---------------------------------------------------------------------------
class TestCombinedEquity:

    def test_faith_2027_combined(self, planner):
        """2027: Grant 1 quarterly + Grant 2 beyond vest = expected total."""
        grant1 = RSUGrant(
            id="grant_1_2025",
            grant_date=date(2025, 10, 10),
            total_shares=3951,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1975,
            periodic_shares=494,
            cliff_date=date(2026, 10, 10),
            cliff_replaces_first_vest=False,
        )
        grant2 = RSUGrant(
            id="grant_2_2025",
            grant_date=date(2025, 8, 10),
            total_shares=230,
            vesting_pattern="quarterly",
            periodic_shares=57,
        )

        equity = EquityComp(
            ticker="DOCU", current_price=55.59,
            grants=[grant1, grant2],
        )

        inc_2027 = planner.calculate_annual_rsu_income(2027, equity)
        # Grant 1: 1,976 shares (4 quarterly)
        # Grant 2: 0 shares (all 230 vested by end of 2026)
        expected_shares = 1976
        assert inc_2027 == pytest.approx(expected_shares * 55.59, rel=1e-3)
