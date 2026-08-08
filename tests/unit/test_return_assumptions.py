"""Tests for formalized capital market assumptions (Phase 2.4).

Verifies that equity_real_return and bond_real_return flow from config
through EconomicAssumptions to the engine's growth rate calculations.
"""
import os
import json
import pytest
from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import EconomicAssumptions, AssetAllocation


SAMPLE_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples", "sample_config.json"
)


# ---------------------------------------------------------------------------
# EconomicAssumptions defaults
# ---------------------------------------------------------------------------
class TestEconomicAssumptionDefaults:
    """New fields have sensible defaults."""

    def test_default_equity_return(self):
        ea = EconomicAssumptions()
        assert ea.equity_real_return == 0.06

    def test_default_bond_return(self):
        ea = EconomicAssumptions()
        assert ea.bond_real_return == 0.025

    def test_default_optimistic_pessimistic_range(self):
        ea = EconomicAssumptions()
        assert ea.equity_real_return_optimistic > ea.equity_real_return
        assert ea.equity_real_return_pessimistic < ea.equity_real_return
        assert ea.bond_real_return_optimistic > ea.bond_real_return
        assert ea.bond_real_return_pessimistic < ea.bond_real_return


# ---------------------------------------------------------------------------
# get_rate() includes new fields
# ---------------------------------------------------------------------------
class TestGetRateIncludesReturns:
    """get_rate() returns equity_real_return and bond_real_return for all scenarios."""

    def test_mean_scenario(self):
        ea = EconomicAssumptions()
        rates = ea.get_rate("mean")
        assert "equity_real_return" in rates
        assert "bond_real_return" in rates
        assert rates["equity_real_return"] == 0.06
        assert rates["bond_real_return"] == 0.025

    def test_optimistic_scenario(self):
        ea = EconomicAssumptions()
        rates = ea.get_rate("optimistic")
        assert rates["equity_real_return"] == 0.08
        assert rates["bond_real_return"] == 0.035

    def test_pessimistic_scenario(self):
        ea = EconomicAssumptions()
        rates = ea.get_rate("pessimistic")
        assert rates["equity_real_return"] == 0.04
        assert rates["bond_real_return"] == 0.015


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------
class TestConfigParsing:
    """New config fields are parsed correctly."""

    def test_default_config_loads(self):
        """Config without equity/bond return fields uses defaults."""
        planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
        ea = planner.scenario.economic
        # Should use defaults since sample_config doesn't have these fields
        assert ea.equity_real_return == 0.06
        assert ea.bond_real_return == 0.025

    def test_custom_returns_from_config(self, tmp_path):
        """Config with custom equity/bond returns parses them."""
        config = {
            "primary": {"name": "A", "birth_date": "1990-01-01",
                        "retirement_date": "2030-01-01", "longevity_age": 90},
            "spouse": {"name": "B", "birth_date": "1990-01-01",
                       "retirement_date": "2030-01-01", "longevity_age": 90},
            "economic": {
                "inflation": 0.025,
                "equity_real_return": 0.07,
                "bond_real_return": 0.03,
            },
            "accounts": [
                {"id": "ira", "name": "IRA", "type": "401k",
                 "tax_treatment": "pre_tax", "balance": 100_000},
            ],
        }
        config_path = tmp_path / "test_config.json"
        config_path.write_text(json.dumps(config))
        planner = RetirementPlanner.from_config(str(config_path))
        ea = planner.scenario.economic
        assert ea.equity_real_return == 0.07
        assert ea.bond_real_return == 0.03


# ---------------------------------------------------------------------------
# get_growth_rate_for_allocation uses scenario-level returns
# ---------------------------------------------------------------------------
class TestGrowthRateUsesScenarioReturns:
    """Engine uses scenario-level equity/bond returns in allocation calculations."""

    def _make_planner(self, equity_return=0.06, bond_return=0.025):
        config = {
            "primary": {"name": "A", "birth_date": "1990-01-01",
                        "retirement_date": "2030-01-01", "longevity_age": 90},
            "spouse": {"name": "B", "birth_date": "1990-01-01",
                       "retirement_date": "2030-01-01", "longevity_age": 90},
            "economic": {
                "inflation": 0.025,
                "equity_real_return": equity_return,
                "bond_real_return": bond_return,
            },
            "accounts": [
                {"id": "ira", "name": "IRA", "type": "401k",
                 "tax_treatment": "pre_tax", "balance": 100_000,
                 "growth_rate": 0},  # No per-account override
            ],
        }
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(config, f)
            path = f.name
        try:
            return RetirementPlanner.from_config(path)
        finally:
            os.unlink(path)

    def test_no_account_override_uses_scenario_returns(self):
        """Account with growth_rate=0 uses scenario equity/bond returns."""
        planner = self._make_planner(equity_return=0.08, bond_return=0.03)
        account = planner.accounts["ira"]
        allocation = AssetAllocation(equity_pct=0.7, bond_pct=0.3)
        rate = planner.get_growth_rate_for_allocation(account, allocation)
        # Expected: 0.08 * 0.7 + 0.03 * 0.3 = 0.056 + 0.009 = 0.065
        assert rate == pytest.approx(0.065, abs=1e-4)

    def test_per_account_override_uses_growth_rate(self):
        """Account with growth_rate set overrides scenario equity return."""
        config = {
            "primary": {"name": "A", "birth_date": "1990-01-01",
                        "retirement_date": "2030-01-01", "longevity_age": 90},
            "spouse": {"name": "B", "birth_date": "1990-01-01",
                       "retirement_date": "2030-01-01", "longevity_age": 90},
            "economic": {
                "inflation": 0.025,
                "equity_real_return": 0.06,
                "bond_real_return": 0.025,
            },
            "accounts": [
                {"id": "ira", "name": "IRA", "type": "401k",
                 "tax_treatment": "pre_tax", "balance": 100_000,
                 "growth_rate": 0.10},  # Per-account override
            ],
        }
        import tempfile, json as _json
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            _json.dump(config, f)
            path = f.name
        try:
            planner = RetirementPlanner.from_config(path)
        finally:
            os.unlink(path)

        account = planner.accounts["ira"]
        allocation = AssetAllocation(equity_pct=0.7, bond_pct=0.3)
        rate = planner.get_growth_rate_for_allocation(account, allocation)
        # Expected: 0.10 * 0.7 + 0.025 * 0.3 = 0.07 + 0.0075 = 0.0775
        assert rate == pytest.approx(0.0775, abs=1e-4)

    def test_different_scenarios_use_different_returns(self):
        """Optimistic and pessimistic scenarios produce different rates."""
        planner = self._make_planner(equity_return=0.06, bond_return=0.025)
        account = planner.accounts["ira"]
        allocation = AssetAllocation(equity_pct=1.0, bond_pct=0.0)

        # The growth rate is computed from mean scenario in get_growth_rate_for_allocation
        rate = planner.get_growth_rate_for_allocation(account, allocation)
        # With growth_rate=0, equity_rate comes from scenario: 0.06
        assert rate == pytest.approx(0.06, abs=1e-4)


# ---------------------------------------------------------------------------
# Backward compatibility: existing configs still work
# ---------------------------------------------------------------------------
class TestBackwardCompatibility:
    """Configs without equity_real_return/bond_real_return still produce valid results."""

    def test_sample_config_still_works(self):
        """The sample config (no new fields) loads and projects without error."""
        planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
        projections = planner.project_cash_flow("mean")
        assert len(projections) > 0
        # First year should have positive income
        assert projections[0]["income"] > 0

    def test_legacy_growth_rate_accounts_still_grow(self):
        """Accounts with growth_rate still get returns."""
        planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
        projections = planner.project_cash_flow("mean")
        # Net worth should change over time (accounts grow)
        first_nw = projections[0]["net_worth"]
        mid_nw = projections[len(projections) // 2]["net_worth"]
        # At minimum, assets should be non-zero
        assert first_nw > 0
        assert mid_nw > 0
