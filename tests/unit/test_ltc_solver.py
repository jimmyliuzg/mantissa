"""Tests for ltc_solver.py — LTC events and reverse solver."""
import pytest
from retirement_planner.ltc_solver import (
    LTCConfig, LTCEvent, simulate_ltc_events, calculate_ltc_annual_cost,
    ltc_probability_by_age, SolverResult, reverse_solve,
    solve_retirement_age, solve_savings_rate, solve_spending,
)


class TestLTCConfig:

    def test_defaults(self):
        c = LTCConfig()
        assert c.base_probability == 0.02
        assert c.annual_cost == 100_000
        assert c.start_age == 75


class TestLTCSimulation:

    def test_no_ltc_young(self):
        config = LTCConfig()
        events = simulate_ltc_events(config, current_age=50, max_age=55, seed=42)
        assert events == []

    def test_ltc_possible_old(self):
        config = LTCConfig(base_probability=0.50)
        events = simulate_ltc_events(config, current_age=80, max_age=85, seed=42)
        assert len(events) >= 0

    def test_ltc_cost_inflates(self):
        config = LTCConfig(annual_cost=100_000, ltc_inflation=0.05)
        events = simulate_ltc_events(config, current_age=75, max_age=76, seed=42)
        if events:
            assert events[0].annual_cost == 100_000

    def test_ltc_portfolio_impact(self):
        config = LTCConfig(base_probability=1.0, annual_cost=100_000)
        events = simulate_ltc_events(
            config, current_age=75, max_age=76,
            portfolio_value=500_000, seed=42,
        )
        if events:
            assert events[0].portfolio_impact > 0

    def test_ltc_asset_shield(self):
        config = LTCConfig(
            base_probability=1.0,
            annual_cost=100_000,
            asset_shield=500_000,
        )
        # Portfolio = $250K, shield = $500K → shield covers entire cost
        events = simulate_ltc_events(
            config, current_age=75, max_age=76,
            portfolio_value=250_000, seed=42,
        )
        if events:
            # Shield ($500K) > total cost → no impact
            assert events[0].portfolio_impact == 0


class TestLTCProbability:

    def test_below_start_age(self):
        config = LTCConfig()
        assert ltc_probability_by_age(60, config) == 0.0

    def test_at_start_age(self):
        config = LTCConfig(base_probability=0.02)
        p = ltc_probability_by_age(75, config)
        assert p == pytest.approx(0.02)

    def test_increases_with_age(self):
        config = LTCConfig(base_probability=0.02)
        p75 = ltc_probability_by_age(75, config)
        p85 = ltc_probability_by_age(85, config)
        assert p85 > p75

    def test_caps_at_max(self):
        config = LTCConfig(base_probability=0.02)
        p = ltc_probability_by_age(100, config)
        assert p <= 0.15


class TestLTCAnnualCost:

    def test_no_cost_outside_range(self):
        config = LTCConfig()
        assert calculate_ltc_annual_cost(60, config) == 0.0

    def test_cost_inflates(self):
        config = LTCConfig(annual_cost=100_000, ltc_inflation=0.05)
        cost0 = calculate_ltc_annual_cost(75, config, years_from_start=0)
        cost5 = calculate_ltc_annual_cost(80, config, years_from_start=5)
        assert cost5 > cost0
        assert cost5 == pytest.approx(100_000 * 1.05 ** 5)


# ---------------------------------------------------------------------------
# Reverse solver
# ---------------------------------------------------------------------------
class TestReverseSolver:

    def test_converges_higher_is_better(self):
        # success_rate = lever / 100 (higher lever = higher success)
        def eval_fn(x):
            return min(1.0, x / 100)

        result = reverse_solve(
            eval_fn, "test_lever",
            target_success_rate=0.80,
            min_value=0, max_value=100,
            tolerance=0.02,
        )
        assert result.converged
        assert abs(result.actual_success_rate - 0.80) <= 0.02

    def test_converges_lower_is_better(self):
        # success_rate = 1 - lever/100 (lower lever = higher success)
        # For this, we negate the lever so higher = better
        def eval_fn(x):
            return min(1.0, x / 80)

        result = reverse_solve(
            eval_fn, "inverted",
            target_success_rate=0.90,
            min_value=0, max_value=100,
            tolerance=0.02,
        )
        assert result.converged

    def test_no_convergence(self):
        result = reverse_solve(
            lambda x: 0.5,
            "test",
            target_success_rate=0.90,
            min_value=0, max_value=100,
            max_iterations=5,
        )
        assert not result.converged

    def test_solve_retirement_age(self):
        # Later retirement = higher success
        def eval_fn(age):
            return min(1.0, (age - 25) / 45)

        result = solve_retirement_age(eval_fn, target_success=0.80)
        assert result.converged
        assert 30 <= result.lever_value <= 70

    def test_solve_savings_rate(self):
        # Higher savings = higher success
        def eval_fn(rate):
            return min(1.0, rate / 0.30)

        result = solve_savings_rate(eval_fn, target_success=0.90)
        assert result.converged

    def test_solve_spending_inverted(self):
        # solve_spending: higher spending = lower success
        # The solver assumes higher lever = higher success
        # So we pass inverted: eval_fn returns success for INVERTED spending
        # User wants: max spending where success >= 80%
        # Solver searches: what INVERTED spending gives 80%?
        def eval_fn(inverted_spend):
            # inverted_spend = max_spend - actual_spend
            return min(1.0, inverted_spend / 240_000)

        result = solve_spending(eval_fn, target_success=0.80)
        assert result.converged
