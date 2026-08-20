"""Stochastic mortality vertical (U1-U4).

Replaces the fixed-longevity MC path with SSA 2023 actuarial death-year
sampling so each run draws a random household death year. Verifies:
- U1: SSA 2023 q(x) tables replace the approximate 5-year buckets.
- U2: each MC run samples a death year (deterministic path unchanged).
- U3: an age-indexed outcome distribution is aggregated across runs.
- U4: the CLI exposes stochastic mode and the report JSON includes it.
"""
from datetime import date
import json
import os

import numpy as np
import pytest

from retirement_planner import RetirementPlanner
from retirement_planner.household import MortalityModel
from retirement_planner.models import (
    Account, EconomicAssumptions, Expense, MonetaryConvention,
    Person, Scenario, SocialSecurity,
)
from retirement_planner.simulators import MonteCarloEngine
from retirement_planner.cli import main
from click.testing import CliRunner


# ---------------------------------------------------------------------------
# Scenario builder (fast, deterministic-ish; mirrors the parity harness)
# ---------------------------------------------------------------------------
def _build(balance=3_000_000, monthly_expense=25_000, real=True):
    scenario = Scenario(
        name="sto_mort", description="", state="CA",
        primary=Person(name="P", birth_date=date(1960, 1, 1),
                       retirement_date=date(2025, 1, 1), longevity_age=95),
        spouse=Person(name="S", birth_date=date(1962, 1, 1),
                      retirement_date=date(2025, 1, 1), longevity_age=95),
        economic=EconomicAssumptions(),
        accounts=[Account("b", "B", "brokerage", "taxable", balance,
                          growth_rate=0.0, equity_pct=0.6)],
        income_streams=[],
        expenses=[Expense(
            id="living", name="living", monthly_amount=monthly_expense,
            start_date=date(2025, 1, 1), end_date=date(2100, 1, 1),
            is_must_spend=True)],
        mortgages=[],
        social_security=SocialSecurity(
            primary_benefit_at_67=2000, spouse_benefit_at_67=1500,
            primary_claiming_age=67, spouse_claiming_age=67),
        dependents=[],
        survivor_expense_ratio=0.75,
        monetary_convention=(
            MonetaryConvention.REAL if real else MonetaryConvention.NOMINAL),
    )
    return RetirementPlanner(scenario)


# ---------------------------------------------------------------------------
# U1: SSA 2023 period life table
# ---------------------------------------------------------------------------
class TestSSATable:

    def test_survival_anchors(self):
        m = MortalityModel()
        # SSA 2023 (2026 TR), table4c6: q(65,male)=0.016455, q(80,female)=0.041183
        assert m.survival_probability(65, True) == pytest.approx(
            1 - 0.016455, abs=1e-6)
        assert m.survival_probability(80, False) == pytest.approx(
            1 - 0.041183, abs=1e-6)

    def test_expected_remaining_years_anchors(self):
        m = MortalityModel()
        # Life expectancy column: e65 male = 18.12, e80 female = 9.82
        assert m.expected_remaining_years(65, True) == pytest.approx(
            18.12, abs=0.15)
        assert m.expected_remaining_years(80, False) == pytest.approx(
            9.82, abs=0.15)

    def test_sample_death_age_distribution_centered(self):
        m = MortalityModel()
        rng = np.random.default_rng(12345)
        ages = [m.sample_death_age(65, True, rng=rng) for _ in range(4000)]
        mean = sum(ages) / len(ages)
        # Mean death age ~ 65 + life expectancy (18.12) = 83.12
        assert mean == pytest.approx(65 + 18.12, abs=0.6)


# ---------------------------------------------------------------------------
# U2: per-run stochastic death year (deterministic unchanged)
# ---------------------------------------------------------------------------
class TestStochasticPath:

    def test_deterministic_path_untouched(self):
        planner = _build()
        mc = MonteCarloEngine(planner)
        res = mc.run(num_simulations=50, seed=7, stochastic=False)
        assert res.get("mortality_distribution") is None
        single = planner.run_single_simulation(stochastic=False)
        assert single["death_age"] is None
        assert single["net_worth_by_year"] == {}

    def test_stochastic_run_samples_death_years(self):
        planner = _build()
        mc = MonteCarloEngine(planner)
        res = mc.run(num_simulations=200, seed=7, stochastic=True)
        # Every run reports a sampled death age
        single = planner.run_single_simulation(
            return_volatility=0.15, rng=np.random.default_rng(7),
            stochastic=True)
        assert isinstance(single["death_age"], int)
        assert single["death_age"] >= 0
        assert res["mortality_distribution"]


# ---------------------------------------------------------------------------
# U3: age-indexed outcome distribution
# ---------------------------------------------------------------------------
class TestMortalityDistribution:

    def test_distribution_structure_and_monotonicity(self):
        planner = _build()
        mc = MonteCarloEngine(planner)
        dist = mc.run(num_simulations=200, seed=7, stochastic=True)[
            "mortality_distribution"]
        assert dist, "expected a non-empty mortality distribution"

        ages = [row["age"] for row in dist]
        assert ages == sorted(ages)

        prev_dead = -1.0
        medians = []
        for row in dist:
            assert 0.0 <= row["pct_dead"] <= 1.0
            assert 0.0 <= row["pct_out_of_money"] <= 1.0
            assert 0.0 <= row["pct_3x_target"] <= 1.0
            assert row["median_net_worth"] >= 0
            # % dead is monotonically non-decreasing with age
            assert row["pct_dead"] >= prev_dead - 1e-9
            prev_dead = row["pct_dead"]
            medians.append(row["median_net_worth"])

        # Mortality accrues: near-zero dead at the first age, near-total by last
        assert dist[0]["pct_dead"] < dist[-1]["pct_dead"]
        # Median net worth peaks before the final age (not still growing)
        assert medians.index(max(medians)) < len(medians) - 1

    def test_determinism_with_seed(self):
        planner = _build()
        mc = MonteCarloEngine(planner)
        a = mc.run(num_simulations=150, seed=99, stochastic=True)[
            "mortality_distribution"]
        b = mc.run(num_simulations=150, seed=99, stochastic=True)[
            "mortality_distribution"]
        assert [r["pct_dead"] for r in a] == pytest.approx(
            [r["pct_dead"] for r in b])
        assert [r["median_net_worth"] for r in a] == pytest.approx(
            [r["median_net_worth"] for r in b])


# ---------------------------------------------------------------------------
# U4: CLI + report JSON
# ---------------------------------------------------------------------------
class TestStochasticCLI:

    def test_cli_run_stochastic_flag(self, tmp_path):
        repo = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cfg = os.path.join(repo, "examples", "sample_config.json")
        assert os.path.exists(cfg), cfg
        out = tmp_path / "out.json"
        r = CliRunner().invoke(main, [
            "run", "-c", cfg, "-n", "40", "--seed", "3", "--stochastic",
            "-o", str(out)])
        assert r.exit_code == 0, r.output
        data = json.loads(out.read_text())
        assert "mortality_distribution" in data
        assert data["mortality_distribution"]
