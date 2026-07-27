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
    ) -> Dict:
        """Run one year-by-year simulation.

        When *method* == "historical" and *historical_returns* is provided,
        those sequential returns replace the gaussian random draws.
        """
        if method == "historical" and historical_returns is not None:
            # Monkey-patch the planner's annual return generation for this sim.
            # We pass the pre-computed return sequence into run_single_simulation
            # via a thin wrapper that overrides the volatility-based return.
            return self._run_historical_simulation(historical_returns, scenario)

        return self.planner.run_single_simulation(scenario, return_volatility)

    def _run_historical_simulation(
        self,
        historical_returns: List[float],
        scenario: str = "mean",
    ) -> Dict:
        """Run a simulation using pre-computed sequential historical returns.

        This wraps planner.run_single_simulation but overrides the return
        generation logic by temporarily injecting a custom return sequence
        into the planner.  We achieve this by patching the planner's
        ``_historical_return_override`` attribute.
        """
        self.planner._historical_return_override = historical_returns
        try:
            return self.planner.run_single_simulation(scenario, return_volatility=0.0)
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
    ) -> Dict:
        """
        Run Monte Carlo simulation and return statistics.

        Args:
            num_simulations: Number of simulations to run
            scenario: Economic scenario (mean, optimistic, pessimistic)
            return_volatility: Standard deviation of returns (used for gaussian)
            method: "gaussian" for random normal returns, "historical" to
                    replay actual S&P 500 annual return sequences

        Returns:
            Dictionary with success rate, percentiles, etc.
        """
        results = []

        if method == "historical":
            num_data_points = len(HISTORICAL_YEARS)
            for _ in range(num_simulations):
                # Pick a random starting year index into the historical data
                start_idx = random.randint(0, num_data_points - 1)
                # Need enough returns to cover the full simulation horizon
                # (typically ~60 years from now to longevity age)
                seq = self._get_return_sequence(start_idx, num_years=100)
                result = self._run_single_simulation(
                    scenario=scenario,
                    method="historical",
                    historical_returns=seq,
                )
                results.append(result)
        else:
            # Gaussian method (original behavior)
            for _ in range(num_simulations):
                result = self.planner.run_single_simulation(scenario, return_volatility)
                results.append(result)

        # Calculate statistics
        success_count = sum(1 for r in results if r["success"])
        success_rate = success_count / num_simulations

        final_nws = sorted([r["final_net_worth"] for r in results])
        peak_nws = sorted([r["peak_net_worth"] for r in results])
        taxes = sorted([r["lifetime_taxes"] for r in results])

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
