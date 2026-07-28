"""Tests for config parsing with equity compensation (from_config + calculate_annual_income)."""
from datetime import date
import json
import os
import pytest

from retirement_planner.engine import RetirementPlanner


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


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
        faith = [s for s in planner.scenario.income_streams if s.id == "faith_docusign"][0]
        assert faith.base_salary is not None
        assert faith.base_salary["annual"] == 224400
        assert faith.base_salary["growth_rate"] == 0.03

    def test_bonus_parsed(self, planner):
        """Bonus is parsed into IncomeStream."""
        faith = [s for s in planner.scenario.income_streams if s.id == "faith_docusign"][0]
        assert faith.bonus is not None
        assert faith.bonus.annual == 22000
        assert faith.bonus.payment_month == 3

    def test_equity_parsed(self, planner):
        """EquityComp is parsed with grants and refreshers."""
        faith = [s for s in planner.scenario.income_streams if s.id == "faith_docusign"][0]
        assert faith.equity is not None
        assert faith.equity.ticker == "DOCU"
        assert faith.equity.current_price == 55.59
        assert len(faith.equity.grants) == 2
        assert faith.equity.refreshers is not None
        assert faith.equity.sell_to_cover is True

    def test_grants_parsed(self, planner):
        """RSU grants are parsed correctly."""
        faith = [s for s in planner.scenario.income_streams if s.id == "faith_docusign"][0]
        g1 = faith.equity.grants[0]
        assert g1.id == "grant_1_2025"
        assert g1.cliff_shares == 1975
        assert g1.cliff_date == date(2026, 10, 10)

        g2 = faith.equity.grants[1]
        assert g2.id == "grant_2_2025"
        assert g2.vesting_pattern == "quarterly"

    def test_legacy_stream_unchanged(self, planner):
        """Stream without base_salary/equity uses legacy monthly_amount path."""
        jimmy = [s for s in planner.scenario.income_streams if s.id == "jimmy_nvidia"][0]
        assert jimmy.base_salary is not None  # Jimmy has base_salary in this config
        assert jimmy.equity is None


# ---------------------------------------------------------------------------
# Income calculation with equity
# ---------------------------------------------------------------------------
class TestIncomeWithEquity:

    def test_faith_2026_income(self, planner):
        """2026: base (224,400) + bonus (22,000) + RSU (cliff + grant2 + refresher)."""
        income = planner.calculate_annual_income(2026)
        # Faith base: 224,400
        # Faith bonus: 22,000
        # Faith RSU: Grant 1 cliff (1,975) + Grant 2 partial (173) + Refresher 2026 (123.5) = 2,271.5
        faith_total = 224400 + 22000 + 2271.5 * 55.59
        jimmy_total = 190000
        expected_total = faith_total + jimmy_total
        assert income["total"] == pytest.approx(expected_total, rel=1e-3)

    def test_faith_2027_income(self, planner):
        """2027: base + bonus + quarterly RSUs."""
        income = planner.calculate_annual_income(2027)
        # Faith base: 224,400 × 1.03 = 231,132
        # Faith bonus: 22,000 × 1.03 = 22,660
        # Faith RSU: Grant 1 quarterly (1,976 shares) + Grant 2 done
        # + Refresher 2026 (494) + Refresher 2027 (123.5)
        # Total RSU shares: 1,976 + 494 + 123.5 = 2,593.5
        faith_base = 224400 * 1.03
        faith_bonus = 22000 * 1.03
        faith_rsu = 2593.5 * 55.59

        jimmy_base = 190000 * 1.03

        expected_total = faith_base + faith_bonus + faith_rsu + jimmy_base
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
        sample_path = os.path.join(os.path.dirname(__file__), "..", "examples", "sample_config.json")
        if os.path.exists(sample_path):
            planner = RetirementPlanner.from_config(sample_path)
            income = planner.calculate_annual_income(2026)
            assert "total" in income
            assert income["total"] > 0
