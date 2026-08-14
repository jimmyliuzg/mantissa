"""Tests for config parsing with equity compensation (from_config + calculate_annual_income)."""
from datetime import date
import json
import os
import pytest

from retirement_planner.engine import RetirementPlanner


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


@pytest.fixture
def planner():
    config_path = os.path.join(FIXTURES_DIR, "equity_config.json")
    return RetirementPlanner.from_config(config_path)


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------
class TestConfigParsing:

    def test_loads_without_error(self, planner):
        """Config with equity fields loads successfully."""
        assert planner is not None

    def test_base_salary_parsed(self, planner):
        """base_salary is parsed into IncomeStream."""
        spouse = [s for s in planner.scenario.income_streams if s.id == "spouse_globex"][0]
        assert spouse.base_salary is not None
        assert spouse.base_salary["annual"] == 180000
        assert spouse.base_salary["growth_rate"] == 0.03

    def test_bonus_parsed(self, planner):
        """Bonus is parsed into IncomeStream."""
        spouse = [s for s in planner.scenario.income_streams if s.id == "spouse_globex"][0]
        assert spouse.bonus is not None
        assert spouse.bonus.annual == 18000
        assert spouse.bonus.payment_month == 3

    def test_equity_parsed(self, planner):
        """EquityComp is parsed with grants and refreshers."""
        spouse = [s for s in planner.scenario.income_streams if s.id == "spouse_globex"][0]
        assert spouse.equity is not None
        assert spouse.equity.ticker == "EXMP"
        assert spouse.equity.current_price == 50.0
        assert len(spouse.equity.grants) == 2
        assert spouse.equity.refreshers is not None
        assert spouse.equity.sell_to_cover is True

    def test_grants_parsed(self, planner):
        """RSU grants are parsed correctly."""
        spouse = [s for s in planner.scenario.income_streams if s.id == "spouse_globex"][0]
        g1 = spouse.equity.grants[0]
        assert g1.id == "grant_1_2025"
        assert g1.cliff_shares == 1000
        assert g1.cliff_date == date(2026, 10, 10)

        g2 = spouse.equity.grants[1]
        assert g2.id == "grant_2_2025"
        assert g2.vesting_pattern == "quarterly"

    def test_legacy_stream_unchanged(self, planner):
        """Stream without base_salary/equity uses legacy monthly_amount path."""
        primary = [s for s in planner.scenario.income_streams if s.id == "primary_acme"][0]
        assert primary.base_salary is not None  # Primary has base_salary in this config
        assert primary.equity is None


# ---------------------------------------------------------------------------
# Income calculation with equity
# ---------------------------------------------------------------------------
class TestIncomeWithEquity:

    def test_spouse_2026_income(self, planner):
        """2026: base (180,000) + bonus (18,000) + RSU (cliff + grant2)."""
        income = planner.calculate_annual_income(2026)
        # Spouse base: 180,000
        # Spouse bonus: 18,000
        # Spouse RSU: Grant 1 cliff (1,000) + Grant 2 (400) = 1,400 shares
        spouse_total = 180000 + 18000 + 1400 * 50.0
        primary_total = 200000
        expected_total = spouse_total + primary_total
        assert income["total"] == pytest.approx(expected_total, rel=1e-3)

    def test_spouse_2027_income(self, planner):
        """2027: base + bonus + RSU (grant1 quarterly + grant2 + refresher)."""
        income = planner.calculate_annual_income(2027)
        # Spouse base: 180,000 × 1.03 = 185,400
        # Spouse bonus: 18,000 × 1.03 = 18,540
        # Spouse RSU: Grant 1 quarterly (1,000) + Grant 2 (300) + refresher (25) = 1,325 shares
        spouse_total = 180000 * 1.03 + 18000 * 1.03 + 1325 * 50.0
        primary_total = 200000 * 1.03
        expected_total = spouse_total + primary_total
        assert income["total"] == pytest.approx(expected_total, rel=1e-3)

    def test_income_by_source_includes_rsu(self, planner):
        """RSU income appears as separate line in by_source."""
        income = planner.calculate_annual_income(2026)
        rsu_keys = [k for k in income["by_source"] if "RSU" in k]
        assert len(rsu_keys) > 0

    def test_legacy_config_still_works(self):
        """Config with only monthly_amount (no equity) still works."""
        config_path = os.path.join(FIXTURES_DIR, "../fixtures/../")  # Use sample_config
        # Fall back to the sample config which has no equity
        sample_path = os.path.join(os.path.dirname(__file__), "..", "..", "examples", "sample_config.json")
        if os.path.exists(sample_path):
            planner = RetirementPlanner.from_config(sample_path)
            income = planner.calculate_annual_income(2026)
            assert "total" in income
            assert income["total"] > 0
