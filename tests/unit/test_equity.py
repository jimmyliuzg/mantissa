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
    primary = Person(name="Primary", birth_date=date(1990, 1, 1),
                     retirement_date=date(2035, 1, 1), longevity_age=90)
    spouse = Person(name="Spouse", birth_date=date(1991, 1, 1),
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
# Grant 1: cliff + quarterly (cliff on top, no replaces)
# ---------------------------------------------------------------------------
class TestGrant1CliffQuarterly:
    """Grant 1: 2,000 total shares, cliff 1,000 at Oct 2026, quarterly 250 after."""

    @pytest.fixture
    def grant1(self):
        return RSUGrant(
            id="grant_1_2025",
            grant_date=date(2025, 10, 10),
            total_shares=2000,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1000,
            periodic_shares=250,
            cliff_date=date(2026, 10, 10),
            cliff_replaces_first_vest=False,
        )

    def test_2025_grant_year(self, planner, grant1):
        """2025: no vest before cliff."""
        assert planner._cliff_quarterly_vests(grant1, 2025) == 0

    def test_2026_cliff_year(self, planner, grant1):
        """2026: cliff only (1,000)."""
        assert planner._cliff_quarterly_vests(grant1, 2026) == 1000

    def test_2027_post_cliff(self, planner, grant1):
        """2027: quarterly only (250×4 = 1,000)."""
        assert planner._cliff_quarterly_vests(grant1, 2027) == 1000

    def test_2028_beyond_vest(self, planner, grant1):
        """2028: all shares already vested."""
        assert planner._cliff_quarterly_vests(grant1, 2028) == 0

    def test_total_vested(self, planner, grant1):
        """Full vest: 1,000 + 1,000 = 2,000."""
        total = sum(planner._cliff_quarterly_vests(grant1, y) for y in range(2025, 2030))
        assert total == 2000


# ---------------------------------------------------------------------------
# Grant 2: quarterly-only (no cliff)
# ---------------------------------------------------------------------------
class TestGrant2Quarterly:
    """Grant 2: 800 total shares, quarterly 100."""

    @pytest.fixture
    def grant2(self):
        return RSUGrant(
            id="grant_2_2025",
            grant_date=date(2025, 8, 10),
            total_shares=800,
            vesting_pattern="quarterly",
            periodic_shares=100,
        )

    def test_2025_grant_year(self, planner, grant2):
        """2025: Aug-Dec = 5 months, 1 quarter → 100 shares."""
        assert planner._quarterly_vests(grant2, 2025) == 100

    def test_2026_full_year(self, planner, grant2):
        """2026: 400 shares (4 quarters)."""
        assert planner._quarterly_vests(grant2, 2026) == 400

    def test_2027_residual(self, planner, grant2):
        """2027: 300 remaining (800 - 100 - 400)."""
        assert planner._quarterly_vests(grant2, 2027) == 300

    def test_2028_beyond_vest(self, planner, grant2):
        """2028: all shares already vested."""
        assert planner._quarterly_vests(grant2, 2028) == 0

    def test_total_vested(self, planner, grant2):
        """Full vest: 100 + 400 + 300 = 800."""
        total = sum(planner._quarterly_vests(grant2, y) for y in range(2025, 2030))
        assert total == 800


# ---------------------------------------------------------------------------
# cliff_replaces_first_vest=True
# ---------------------------------------------------------------------------
class TestCliffReplacesFirstVest:

    @pytest.fixture
    def grant_replaces(self):
        return RSUGrant(
            id="grant_replaces",
            grant_date=date(2025, 10, 10),
            total_shares=2000,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1000,
            periodic_shares=250,
            cliff_date=date(2026, 10, 10),
            cliff_replaces_first_vest=True,
        )

    def test_cliff_year_with_replacement(self, planner, grant_replaces):
        """Cliff year: cliff (1,000) + 3 quarterly (250×3=750) = 1,750."""
        assert planner._cliff_quarterly_vests(grant_replaces, 2026) == 1000 + 250 * 3

    def test_post_cliff_year(self, planner, grant_replaces):
        """After cliff: 1 quarterly remaining (250)."""
        assert planner._cliff_quarterly_vests(grant_replaces, 2027) == 250

    def test_total_vested(self, planner, grant_replaces):
        """Full vest: 1,750 + 250 = 2,000."""
        total = sum(planner._cliff_quarterly_vests(grant_replaces, y) for y in range(2025, 2030))
        assert total == 2000


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
            total_shares=2000,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1000,
            periodic_shares=250,
            cliff_date=date(2026, 10, 10),
        )

    def test_end_date_before_grant(self, planner, grant):
        """Grant created after end_date → skipped entirely."""
        equity = EquityComp(
            ticker="EXMP", current_price=50.0,
            grants=[grant],
            end_date=date(2025, 6, 1),  # before grant
        )
        assert planner.calculate_annual_rsu_income(2026, equity) == 0

    def test_end_date_mid_year(self, planner, grant):
        """Job ends mid-year → no vests after end_date."""
        equity = EquityComp(
            ticker="EXMP", current_price=50.0,
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
            ticker="EXMP", current_price=50.0,
            grants=[],
            refreshers=RefresherPolicy(
                annual_shares=250,
                grant_month=10,
                vesting_pattern="quarterly",
                start_year=2026,
                end_year=2035,
                growth_rate=0.0,
            ),
        )
        # 2026: refresher granted Oct → 1 quarter (62.5 shares)
        inc_2026 = planner.calculate_annual_rsu_income(2026, equity)
        assert inc_2026 == pytest.approx(62.5 * 50.0, rel=1e-3)

        # 2027: Grant 2026 full year (250) + Grant 2027 partial (62.5) = 312.5
        inc_2027 = planner.calculate_annual_rsu_income(2027, equity)
        assert inc_2027 == pytest.approx(312.5 * 50.0, rel=1e-3)

    def test_compounding_refreshers(self, planner):
        """Multiple years of refreshers compound."""
        equity = EquityComp(
            ticker="EXMP", current_price=50.0,
            grants=[],
            refreshers=RefresherPolicy(
                annual_shares=250,
                grant_month=10,
                vesting_pattern="quarterly",
                start_year=2026,
                end_year=2035,
                growth_rate=0.0,
            ),
        )
        # 2028: Grant 2026 (250) + Grant 2027 (250) + Grant 2028 (62.5) = 562.5
        inc_2028 = planner.calculate_annual_rsu_income(2028, equity)
        assert inc_2028 == pytest.approx(562.5 * 50.0, rel=1e-3)

    def test_refresher_with_growth(self, planner):
        """Refresher with 5% annual growth in grant size."""
        equity = EquityComp(
            ticker="EXMP", current_price=50.0,
            grants=[],
            refreshers=RefresherPolicy(
                annual_shares=250,
                grant_month=10,
                vesting_pattern="quarterly",
                start_year=2026,
                end_year=2035,
                growth_rate=0.05,
            ),
        )
        # 2027: Grant 2026 (250) + Grant 2027 (250×1.05=262.5, 1 quarter=65.625)
        inc_2027 = planner.calculate_annual_rsu_income(2027, equity)
        expected_shares = 250 + 262.5 / 4  # 250 + 65.625
        assert inc_2027 == pytest.approx(expected_shares * 50.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Price sensitivity
# ---------------------------------------------------------------------------
class TestPriceSensitivity:

    def test_different_prices(self, planner):
        """Same shares, different price → different income."""
        grant = RSUGrant(
            id="grant_1",
            grant_date=date(2025, 10, 10),
            total_shares=2000,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1000,
            periodic_shares=250,
            cliff_date=date(2026, 10, 10),
        )

        equity_low = EquityComp(ticker="EXMP", current_price=38.0, grants=[grant])
        equity_mid = EquityComp(ticker="EXMP", current_price=50.0, grants=[grant])
        equity_high = EquityComp(ticker="EXMP", current_price=72.0, grants=[grant])

        shares_2026 = planner._cliff_quarterly_vests(grant, 2026)

        assert planner.calculate_annual_rsu_income(2026, equity_low) == shares_2026 * 38.0
        assert planner.calculate_annual_rsu_income(2026, equity_mid) == shares_2026 * 50.0
        assert planner.calculate_annual_rsu_income(2026, equity_high) == shares_2026 * 72.0


# ---------------------------------------------------------------------------
# Combined: Grant 1 + Grant 2
# ---------------------------------------------------------------------------
class TestCombinedEquity:

    def test_2027_combined(self, planner):
        """2027: Grant 1 quarterly + Grant 2 residual = expected total."""
        grant1 = RSUGrant(
            id="grant_1_2025",
            grant_date=date(2025, 10, 10),
            total_shares=2000,
            vesting_pattern="cliff_quarterly",
            cliff_shares=1000,
            periodic_shares=250,
            cliff_date=date(2026, 10, 10),
            cliff_replaces_first_vest=False,
        )
        grant2 = RSUGrant(
            id="grant_2_2025",
            grant_date=date(2025, 8, 10),
            total_shares=800,
            vesting_pattern="quarterly",
            periodic_shares=100,
        )

        equity = EquityComp(
            ticker="EXMP", current_price=50.0,
            grants=[grant1, grant2],
        )

        inc_2027 = planner.calculate_annual_rsu_income(2027, equity)
        # Grant 1: 1,000 shares (4 quarterly) + Grant 2: 300 residual
        expected_shares = 1300
        assert inc_2027 == pytest.approx(expected_shares * 50.0, rel=1e-3)
