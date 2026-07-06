"""
Monte Carlo simulation engine and scenario comparison.
"""
from typing import Dict, List, Optional
import random
from concurrent.futures import ProcessPoolExecutor, as_completed

from .engine import RetirementPlanner


class MonteCarloEngine:
    """Run Monte Carlo simulations for retirement planning."""
    
    def __init__(self, planner: RetirementPlanner):
        self.planner = planner
    
    def run(
        self,
        num_simulations: int = 1000,
        scenario: str = "mean",
        return_volatility: float = 0.15,
        num_workers: int = 4
    ) -> Dict:
        """
        Run Monte Carlo simulation and return statistics.
        
        Args:
            num_simulations: Number of simulations to run
            scenario: Economic scenario (mean, optimistic, pessimistic)
            return_volatility: Standard deviation of returns
            num_workers: Number of parallel workers
            
        Returns:
            Dictionary with success rate, percentiles, etc.
        """
        results = []
        
        # Run simulations
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
            "median_final_nw": final_nws[num_simulations // 2],
            "p10_final_nw": final_nws[num_simulations // 10],
            "p25_final_nw": final_nws[num_simulations // 4],
            "p75_final_nw": final_nws[int(num_simulations * 0.75)],
            "p90_final_nw": final_nws[int(num_simulations * 0.9)],
            "median_peak_nw": peak_nws[num_simulations // 2],
            "median_taxes": taxes[num_simulations // 2],
            "out_of_savings_rate": sum(1 for r in results if r["out_of_savings_year"]) / num_simulations,
        }


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
        num_simulations: int = 1000
    ) -> Dict:
        """Compare Monte Carlo results across scenarios."""
        if scenarios is None:
            scenarios = list(self.planners.keys())
        
        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            mc = MonteCarloEngine(planner)
            comparison[scenario_name] = mc.run(num_simulations)
        
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
    
    def sensitivity_analysis(
        self,
        base_scenario: str,
        variable: str,
        values: List[float]
    ) -> Dict:
        """
        Run sensitivity analysis on a single variable.
        
        Args:
            base_scenario: Name of the base scenario
            variable: Variable to test (e.g., "growth_rate", "inflation")
            values: List of values to test
            
        Returns:
            Dictionary of value -> success_rate
        """
        # TODO: Implement sensitivity analysis
        # This would modify the scenario and re-run Monte Carlo
        pass


class RothConversionOptimizer:
    """Optimize Roth conversion timing and amounts."""
    
    def __init__(self, planner: RetirementPlanner):
        self.planner = planner
    
    def find_optimal_conversions(
        self,
        max_annual_conversion: float = 100_000,
        tax_bracket_target: float = 0.24
    ) -> List[Dict]:
        """
        Find optimal Roth conversion strategy.
        
        Converts during low-income years (early retirement) to stay
        in lower tax brackets.
        
        Returns:
            List of conversion recommendations by year
        """
        # TODO: Implement optimization algorithm
        # Key logic:
        # 1. Identify low-income years (post-retirement, pre-SS)
        # 2. Calculate how much to convert to fill lower brackets
        # 3. Balance against future tax rates and RMDs
        pass
