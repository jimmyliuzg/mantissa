"""Stress path: min_reduction × stress_level cuts discretionary expenses.

Wired through: calculate_annual_expenses → MC + deterministic loops →
MonteCarloEngine.run → CLI (--stress / `stress` command).
"""
import json
import numpy as np
import pytest
from datetime import date

from retirement_planner import RetirementPlanner, MonteCarloEngine
from retirement_planner.models import (
    Account, EconomicAssumptions, Expense, Person, Scenario,
)


def _planner(stress_config: float = 0.0):
    scenario = Scenario(
        name="s", description="",
        primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
        spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
        economic=EconomicAssumptions(),
        accounts=[Account("b", "B", "brokerage", "taxable", 2_000_000,
                          growth_rate=0.06)],
        income_streams=[], mortgages=[],
        expenses=[
            Expense("must", "Must", monthly_amount=2_000,
                    start_date=date(2026, 1, 1), end_date=date(2090, 12, 31),
                    is_must_spend=True),
            Expense("fun", "Fun", monthly_amount=1_000,
                    start_date=date(2026, 1, 1), end_date=date(2090, 12, 31),
                    is_must_spend=False, min_reduction=0.8),
        ],
    )
    p = RetirementPlanner(scenario)
    p.stress_level = stress_config
    return p


class TestExpenseStress:
    def test_stress_cuts_discretionary_only(self):
        p = _planner()
        exp = p.calculate_annual_expenses(2030, stress_level=1.0)
        assert exp["by_category"]["Must"] == pytest.approx(24_000)
        # Fun: 12,000 × (1 − 0.8×1.0) = 2,400
        assert exp["by_category"]["Fun"] == pytest.approx(2_400, rel=1e-6)

    def test_partial_stress_scales_linearly(self):
        p = _planner()
        exp = p.calculate_annual_expenses(2030, stress_level=0.5)
        assert exp["by_category"]["Fun"] == pytest.approx(
            12_000 * (1 - 0.8 * 0.5), rel=1e-6)

    def test_zero_min_reduction_never_cuts(self):
        p = _planner()
        p.scenario.expenses[1].min_reduction = 0.0
        exp = p.calculate_annual_expenses(2030, stress_level=1.0)
        assert exp["by_category"]["Fun"] == pytest.approx(12_000, rel=1e-6)

    def test_stress_level_clamped(self):
        p = _planner()
        exp = p.calculate_annual_expenses(2030, stress_level=2.0)
        # clamped to 1.0 → same as full stress
        assert exp["by_category"]["Fun"] == pytest.approx(2_400, rel=1e-6)


class TestStressBothPaths:
    def test_deterministic_stress_param(self):
        p = _planner()
        base = {r["year"]: r["expenses"] for r in p.project_cash_flow()}
        stress = {r["year"]: r["expenses"]
                  for r in p.project_cash_flow(stress_level=1.0)}
        assert stress[2030] < base[2030]
        # Must-spend unchanged: diff = exactly the Fun cut
        diff = base[2030] - stress[2030]
        assert diff == pytest.approx(12_000 * 0.8, rel=1e-6)

    def test_planner_level_default(self):
        p = _planner(stress_config=0.5)
        rows = p.project_cash_flow()
        assert rows[4]["expenses"] == pytest.approx(
            24_000 + 12_000 * (1 - 0.8 * 0.5), rel=1e-6)

    def test_mc_stress_param(self):
        p = _planner()
        rng = np.random.default_rng(3)
        base = p.run_single_simulation(return_volatility=0.0, rng=rng)
        rng = np.random.default_rng(3)
        stress = p.run_single_simulation(
            return_volatility=0.0, rng=rng, stress_level=1.0)
        assert stress["final_net_worth"] > base["final_net_worth"]
        assert stress["lifetime_taxes"] <= base["lifetime_taxes"]

    def test_mc_engine_passthrough(self):
        p = _planner()
        mc = MonteCarloEngine(p)
        r_base = mc.run(num_simulations=20, seed=4)
        r_stress = mc.run(num_simulations=20, seed=4, stress_level=1.0)
        assert r_stress["median_final_nw"] > r_base["median_final_nw"]

    def test_mc_engine_historical_passthrough(self):
        p = _planner()
        mc = MonteCarloEngine(p)
        r_base = mc.run(num_simulations=10, method="historical", seed=4)
        r_stress = mc.run(num_simulations=10, method="historical", seed=4,
                          stress_level=1.0)
        assert r_stress["median_final_nw"] > r_base["median_final_nw"]

    def test_parity_under_stress(self):
        """Both paths apply stress identically → expense rows still agree."""
        import sys
        sys.path.insert(0, "tests/regression")
        from test_mc_deterministic_parity import make, both_paths
        p = make(True, True, False)
        for e in p.scenario.expenses:
            e.min_reduction = 0.5
            e.is_must_spend = False
        det, mc = both_paths(p)  # planner-level stress 0
        p2 = make(True, True, False)
        for e in p2.scenario.expenses:
            e.min_reduction = 0.5
            e.is_must_spend = False
        det2 = {r["year"]: r for r in p2.project_cash_flow(stress_level=0.7)}
        mc2 = {r["year"]: r for r in p2.run_single_simulation(
            return_volatility=0.0, stress_level=0.7,
            collect_projections=True)["projections"]}
        for year in det2:
            assert det2[year]["expenses"] == pytest.approx(
                mc2[year]["expenses"], rel=1e-9)
            assert det2[year]["expenses"] < det[year]["expenses"]


class TestStressConfig:
    def test_from_config_stress_level(self):
        cfg = {
            "name": "s", "description": "", "stress_level": 0.4,
            "primary": {"name": "P", "birth_date": "1980-01-01",
                        "retirement_date": "2026-01-01"},
            "spouse": {"name": "S", "birth_date": "1982-01-01",
                       "retirement_date": "2026-01-01"},
            "accounts": [{"id": "b", "name": "B", "type": "brokerage",
                          "tax_treatment": "taxable", "balance": 100_000}],
            "income_streams": [], "expenses": [], "mortgages": [],
        }
        with open("/tmp/_stress_test.json", "w") as f:
            json.dump(cfg, f)
        p = RetirementPlanner.from_config("/tmp/_stress_test.json")
        assert p.stress_level == 0.4

    def test_config_stress_level_validated(self):
        from retirement_planner.config.validation import validate_config
        issues_hi = validate_config({"stress_level": 1.5}).issues
        issues_lo = validate_config({"stress_level": -0.1}).issues
        issues_ok = validate_config({"stress_level": 0.7}).issues
        assert any(i.path == "$.stress_level" and "<= 1" in i.message
                   for i in issues_hi)
        assert any(i.path == "$.stress_level" and ">= 0" in i.message
                   for i in issues_lo)
        assert not any(i.path == "$.stress_level" for i in issues_ok)
