"""
Sensitivity analysis for retirement plans.

Tests how varying one variable affects outcomes by running
Monte Carlo simulations across a range of values.
"""
import copy
from typing import Dict, List


class SensitivityAnalyzer:
    """Run sensitivity analysis on a retirement plan."""

    def __init__(self, planner):
        self.planner = planner

    def run(
        self,
        variable: str,
        values: List[float],
        num_simulations: int = 100,
    ) -> List[Dict]:
        """Test how varying one variable affects outcomes.

        For each value: modifies planner scenario, runs MC simulations,
        records success rate and avg final net worth.

        Returns list of dicts with keys:
            variable, value, success_rate, avg_final_nw, num_simulations
        """
        original_scenario = copy.deepcopy(self.planner.scenario)
        results = []

        try:
            for value in values:
                self._set_variable(variable, value, self.planner.scenario)

                success_count = 0
                total_final_nw = 0.0

                for _ in range(num_simulations):
                    sim = self.planner.run_single_simulation()
                    if sim["success"]:
                        success_count += 1
                    total_final_nw += sim["final_net_worth"]

                results.append({
                    "variable": variable,
                    "value": value,
                    "success_rate": success_count / num_simulations,
                    "avg_final_nw": total_final_nw / num_simulations,
                    "num_simulations": num_simulations,
                })
        finally:
            self.planner.scenario = original_scenario

        return results

    def _set_variable(self, variable: str, value: float, scenario) -> None:
        """Set a variable on the scenario object.

        Supported variables:
          - "inflation" → scenario.economic.general_inflation
          - "medical_inflation" → scenario.economic.medical_inflation
          - "housing_appreciation" → scenario.economic.housing_appreciation
          - "investment_return_mean" → all non-real_estate/vehicle/checking
            account.growth_rate
        """
        if variable == "inflation":
            scenario.economic.general_inflation = value
            scenario.economic.ss_cola = value
        elif variable == "medical_inflation":
            scenario.economic.medical_inflation = value
        elif variable == "housing_appreciation":
            scenario.economic.housing_appreciation = value
        elif variable == "investment_return_mean":
            for account in scenario.accounts:
                if account.account_type not in ("real_estate", "vehicle", "checking"):
                    account.growth_rate = value
        else:
            raise ValueError(f"Unsupported sensitivity variable: {variable!r}")
