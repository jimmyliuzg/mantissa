"""
Monte Carlo simulation engine and scenario comparison.

Supports two return-generation methods:
- "gaussian" (default): independent random normal draws each year
- "historical": replay actual historical market return sequences,
  capturing sequence-of-returns risk
"""
from typing import Dict, List, Optional
from itertools import islice, cycle
import random
import numpy as np

from .engine import RetirementPlanner
from .historical_data import HISTORICAL_YEARS, _HISTORICAL_SNP500_VALUES


class MonteCarloEngine:
    """Run Monte Carlo simulations for retirement planning."""
    
    def __init__(self, planner: RetirementPlanner):
        self.planner = planner

    # ------------------------------------------------------------------
    # Single simulation with overrideable return generator
    # ------------------------------------------------------------------
    def _run_single_simulation(
        self,
        scenario: str = "mean",
        return_volatility: float = 0.15,
        method: str = "gaussian",
        historical_returns: Optional[List[float]] = None,
        rng=None,
        stress_level: float = 0.0,
        stochastic: bool = False,
    ) -> Dict:
        """Run one year-by-year simulation.

        When *method* == "historical" and *historical_returns* is provided,
        those sequential returns replace the gaussian random draws. When
        *stochastic* is True, each run samples a random household death year
        from the SSA 2023 mortality tables.
        """
        if method == "historical" and historical_returns is not None:
            # Monkey-patch the planner's annual return generation for this sim.
            # We pass the pre-computed return sequence into run_single_simulation
            # via a thin wrapper that overrides the volatility-based return.
            return self._run_historical_simulation(
                historical_returns, scenario, stress_level=stress_level,
                stochastic=stochastic)

        return self.planner.run_single_simulation(
            scenario, return_volatility, rng=rng, stress_level=stress_level,
            stochastic=stochastic)

    def _run_historical_simulation(
        self,
        historical_returns: List[float],
        scenario: str = "mean",
        stress_level: float = 0.0,
        stochastic: bool = False,
    ) -> Dict:
        """Run a simulation using pre-computed sequential historical returns.

        This wraps planner.run_single_simulation but overrides the return
        generation logic by temporarily injecting a custom return sequence
        into the planner.  We achieve this by patching the planner's
        ``_historical_return_override`` attribute.
        """
        self.planner._historical_return_override = historical_returns
        try:
            return self.planner.run_single_simulation(
                scenario, return_volatility=0.0, stress_level=stress_level,
                stochastic=stochastic)
        finally:
            self.planner._historical_return_override = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        num_simulations: int = 1000,
        scenario: str = "mean",
        return_volatility: float = 0.15,
        method: str = "gaussian",
        seed: Optional[int] = None,
        stress_level: float = 0.0,
        stochastic: bool = False,
    ) -> Dict:
        """
        Run Monte Carlo simulation and return statistics.

        Args:
            num_simulations: Number of simulations to run
            scenario: Economic scenario (mean, optimistic, pessimistic)
            return_volatility: Standard deviation of returns (used for gaussian)
            method: "gaussian" for random normal returns, "historical" to
                    replay actual S&P 500 annual return sequences
            seed: RNG seed for reproducibility
            stress_level: 0.0 (normal) to 1.0 (max discretionary cuts —
                    expenses cut by min_reduction × stress_level)

        Returns:
            Dictionary with success rate, percentiles, etc.
        """
        results = []
        rng = np.random.default_rng(seed)
        historical_rng = random.Random(seed)

        if method == "historical":
            num_data_points = len(HISTORICAL_YEARS)
            for _ in range(num_simulations):
                # Pick a random starting year index into the historical data
                start_idx = historical_rng.randint(0, num_data_points - 1)
                # Need enough returns to cover the full simulation horizon
                # (typically ~60 years from now to longevity age)
                seq = self._get_return_sequence(start_idx, num_years=100)
                result = self._run_single_simulation(
                    scenario=scenario,
                    method="historical",
                    historical_returns=seq,
                    rng=rng,
                    stress_level=stress_level,
                    stochastic=stochastic,
                )
                results.append(result)
        else:
            # Gaussian method (original behavior)
            for _ in range(num_simulations):
                result = self.planner.run_single_simulation(
                    scenario, return_volatility, rng=rng,
                    stress_level=stress_level,
                    stochastic=stochastic,
                )
                results.append(result)

        # Calculate statistics
        success_count = sum(1 for r in results if r["success"])
        success_rate = success_count / num_simulations

        final_nws = sorted([r["final_net_worth"] for r in results])
        peak_nws = sorted([r["peak_net_worth"] for r in results])
        taxes = sorted([r["lifetime_taxes"] for r in results])

        # --- Stochastic mortality distribution (U3) ---
        # Aggregate the per-run death ages and financial outcomes into an
        # age-indexed view: at each age, what fraction of runs are dead,
        # out of money, or 3x+ the legacy goal, plus the median net worth.
        if stochastic:
            primary_birth_year = (
                self.planner.scenario.primary.birth_date.year)
            ages = sorted(
                {a for r in results for a in r.get("net_worth_by_year", {})})
            legacy_goal = self.planner.scenario.legacy_goal
            # %3x target is evaluated on each run's final outcome, so it
            # does not vary by age — compute it once, not per age.
            n_thriving = sum(
                1 for r in results
                if r["final_net_worth"] >= 3 * legacy_goal)
            distribution = []
            for a in ages:
                year_at_age = primary_birth_year + a
                n_dead = sum(
                    1 for r in results
                    if r.get("death_age") is not None and r["death_age"] < a)
                n_broke = sum(
                    1 for r in results
                    if r.get("out_of_savings_year") is not None
                    and r["out_of_savings_year"] <= year_at_age)
                nw_vals = [r["net_worth_by_year"][a]
                           for r in results
                           if a in r.get("net_worth_by_year", {})]
                median_nw = float(np.median(nw_vals)) if nw_vals else 0.0
                distribution.append({
                    "age": a,
                    "pct_dead": n_dead / num_simulations,
                    "pct_out_of_money": n_broke / num_simulations,
                    "pct_3x_target": n_thriving / num_simulations,
                    "median_net_worth": median_nw,
                })
            mortality_distribution = distribution
        else:
            mortality_distribution = None

        return {
            "success_rate": success_rate,
            "num_simulations": num_simulations,
            "scenario": scenario,
            "method": method,
            "median_final_nw": final_nws[int(num_simulations * 0.5)],
            "p10_final_nw": final_nws[int(num_simulations * 0.1)],
            "p25_final_nw": final_nws[int(num_simulations * 0.25)],
            "p75_final_nw": final_nws[int(num_simulations * 0.75)],
            "p90_final_nw": final_nws[int(num_simulations * 0.9)],
            "median_peak_nw": peak_nws[int(num_simulations * 0.5)],
            "median_taxes": taxes[num_simulations // 2],
            "out_of_savings_rate": sum(1 for r in results if r["out_of_savings_year"]) / num_simulations,
            "mortality_distribution": mortality_distribution,
        }

    @staticmethod
    def _get_return_sequence(start_year_index: int, num_years: int) -> List[float]:
        """Get a cyclically-wrapped sequence of historical returns."""
        span = len(_HISTORICAL_SNP500_VALUES)
        cycled = cycle(_HISTORICAL_SNP500_VALUES)
        for _ in range(start_year_index):
            next(cycled)
        return list(islice(cycled, num_years))


class ScenarioComparator:
    """Compare multiple retirement scenarios."""

    def __init__(self, planners: Dict[str, RetirementPlanner]):
        """
        Args:
            planners: Dictionary of scenario_name -> RetirementPlanner
        """
        self.planners = planners

    def compare_cash_flow(self, scenarios: List[str] = None) -> Dict:
        """Compare year-by-year cash flow across scenarios."""
        if scenarios is None:
            scenarios = list(self.planners.keys())

        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            projections = planner.project_cash_flow()
            comparison[scenario_name] = projections

        return comparison

    def compare_monte_carlo(
        self,
        scenarios: List[str] = None,
        num_simulations: int = 1000,
        method: str = "gaussian",
    ) -> Dict:
        """Compare Monte Carlo results across scenarios."""
        if scenarios is None:
            scenarios = list(self.planners.keys())

        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            mc = MonteCarloEngine(planner)
            comparison[scenario_name] = mc.run(num_simulations, method=method)

        return comparison

    def compare_net_worth(self, year: int, scenarios: List[str] = None) -> Dict:
        """Compare net worth at a specific year."""
        if scenarios is None:
            scenarios = list(self.planners.keys())

        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            nw = planner.calculate_net_worth(year)
            comparison[scenario_name] = nw

        return comparison
