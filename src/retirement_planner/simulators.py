"""
Monte Carlo simulation engine and scenario comparison.

Supports two return-generation methods:
- "gaussian" (default): independent random normal draws each year
- "historical": replay actual historical market return sequences,
  capturing sequence-of-returns risk
"""
from typing import Dict, List, Optional
from itertools import islice, cycle
import math
import random
import secrets
import numpy as np

from .engine import RetirementPlanner
from .historical_data import HISTORICAL_YEARS, _HISTORICAL_SNP500_VALUES

MAX_SAFE_SEED = 2**53 - 1


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
                stochastic=stochastic, rng=rng)

        return self.planner.run_single_simulation(
            scenario, return_volatility, rng=rng, stress_level=stress_level,
            stochastic=stochastic)

    def _run_historical_simulation(
        self,
        historical_returns: List[float],
        scenario: str = "mean",
        stress_level: float = 0.0,
        stochastic: bool = False,
        rng=None,
    ) -> Dict:
        """Run a simulation using pre-computed sequential historical returns.

        This wraps planner.run_single_simulation but overrides the return
        generation logic by temporarily injecting a custom return sequence
        into the planner.  We achieve this by patching the planner's
        ``_historical_return_override`` attribute.
        """
        had_override = hasattr(self.planner, "_historical_return_override")
        prior_override = getattr(self.planner, "_historical_return_override", None)
        self.planner._historical_return_override = historical_returns
        try:
            return self.planner.run_single_simulation(
                scenario, return_volatility=0.0, stress_level=stress_level,
                stochastic=stochastic, rng=rng)
        finally:
            if had_override:
                self.planner._historical_return_override = prior_override
            else:
                del self.planner._historical_return_override

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
        if not isinstance(num_simulations, int) or isinstance(num_simulations, bool) or num_simulations < 1:
            raise ValueError("num_simulations must be a positive integer")
        if not isinstance(method, str) or method not in {"gaussian", "historical"}:
            raise ValueError("method must be 'gaussian' or 'historical'")
        if not isinstance(scenario, str) or scenario not in {"mean", "optimistic", "pessimistic"}:
            raise ValueError("scenario must be 'mean', 'optimistic', or 'pessimistic'")
        if isinstance(return_volatility, bool) or not isinstance(return_volatility, (int, float)) or not math.isfinite(return_volatility) or return_volatility < 0:
            raise ValueError("return_volatility must be a finite non-negative number")
        if isinstance(stress_level, bool) or not isinstance(stress_level, (int, float)) or not math.isfinite(stress_level) or not 0 <= stress_level <= 1:
            raise ValueError("stress_level must be a finite number between 0 and 1")
        if not isinstance(stochastic, bool):
            raise ValueError("stochastic must be a boolean")
        if seed is not None and (
            not isinstance(seed, int) or isinstance(seed, bool)
            or seed < 0 or seed > MAX_SAFE_SEED
        ):
            raise ValueError(
                f"seed must be an integer between 0 and {MAX_SAFE_SEED}, or None"
            )

        # Resolve entropy once so a run with seed=None can be replayed by
        # passing the returned effective_seed back into run().
        effective_seed = seed if seed is not None else secrets.randbits(53)
        results = []
        historical_start_indices = []
        rng = np.random.default_rng(effective_seed)
        historical_rng = random.Random(effective_seed)

        if method == "historical":
            num_data_points = len(HISTORICAL_YEARS)
            for _ in range(num_simulations):
                # Pick a random starting year index into the historical data
                start_idx = historical_rng.randint(0, num_data_points - 1)
                historical_start_indices.append(start_idx)
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

        # Per-year net-worth percentiles. Each run emits a Dict[age, nw]
        # in `net_worth_by_year`; we aggregate across runs so the chart
        # can draw a fan band that widens/narrows as the projection
        # gets more uncertain. Keyed by primary_age.
        yearly_percentiles: Dict[int, Dict[str, float]] = {}
        if any(result.get("net_worth_by_year") for result in results):
            ages = sorted({a for r in results
                          for a in r.get("net_worth_by_year", {})})
            for age in ages:
                vals = [r["net_worth_by_year"][age]
                        for r in results
                        if age in r.get("net_worth_by_year", {})]
                if not vals:
                    continue
                vals.sort()
                n = len(vals)
                yearly_percentiles[age] = {
                    "p10": vals[int(n * 0.10)],
                    "p25": vals[int(n * 0.25)],
                    "p50": vals[int(n * 0.50)],
                    "p75": vals[int(n * 0.75)],
                    "p90": vals[int(n * 0.90)],
                }

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

        from .outcomes import aggregate_outcomes
        outcomes = aggregate_outcomes(results, self.planner.start_year,
                                      self.planner.scenario.monetary_convention.value,
                                      self.planner.scenario.legacy_goal)
        result = {
            "success_rate": success_rate,
            "outcomes": outcomes,
            "input_readiness": self.planner.input_readiness,
            "spending_cut_frequency": sum(r["years_with_spending_cuts"] > 0 for r in results) / num_simulations,
            "median_years_with_spending_cuts": float(np.median([r["years_with_spending_cuts"] for r in results])),
            "maximum_spending_cut_fraction": max(r["maximum_spending_cut_fraction"] for r in results),
            "access_failure_rate": 1 - outcomes["account_access_met_rate"] if outcomes["account_access_met_rate"] is not None else None,
            "portfolio_depletion_rate": sum(r.get("portfolio_depletion_year") is not None for r in results) / num_simulations,
            "withdrawal_access_policy": self.planner.scenario.withdrawal_access_policy,
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
            "yearly_percentiles": yearly_percentiles,
            "model_warnings": list(dict.fromkeys(
                warning
                for run_result in results
                for warning in run_result.get("model_warnings", [])
            )),
        }
        result["run_metadata"] = self._build_run_metadata(
            effective_seed=effective_seed,
            method=method,
            scenario=scenario,
            num_simulations=num_simulations,
            stochastic=stochastic,
            return_volatility=return_volatility,
            stress_level=stress_level,
            historical_start_indices=historical_start_indices,
            effective_years=sorted({
                self.planner.scenario.primary.birth_date.year + age
                for run_result in results
                for age in run_result.get("net_worth_by_year", {})
            }),
        )
        return result

    def _build_run_metadata(
        self,
        *,
        effective_seed: int,
        method: str,
        scenario: str,
        num_simulations: int,
        stochastic: bool,
        return_volatility: float,
        stress_level: float,
        historical_start_indices: List[int],
        effective_years: List[int],
    ) -> Dict:
        """Describe the inputs needed to identify and replay this run."""
        try:
            from . import __version__ as model_version
        except ImportError:  # pragma: no cover - package is normally importable
            model_version = "unknown"
        metadata = {
            "schema_version": 1,
            "model_version": model_version,
            "effective_seed": int(effective_seed),
            "method": method,
            "scenario": scenario,
            "simulations": num_simulations,
            "mortality_mode": "stochastic" if stochastic else "deterministic",
            "return_volatility": float(return_volatility),
            "stress_level": float(stress_level),
        }
        fallback_inflation = self.planner.scenario.economic.get_rate(
            scenario)["general_inflation"]

        config_fingerprint = getattr(self.planner, "config_fingerprint", None)
        if callable(config_fingerprint):
            fingerprint = config_fingerprint()
            # The method contract is a fingerprint, not a config serializer.
            # Only accept a scalar value here so accidental mappings cannot
            # leak raw scenario content into result metadata.
            if isinstance(fingerprint, str):
                metadata["config_fingerprint"] = fingerprint
                metadata["fingerprint_kind"] = "resolved_scenario"

        # Rule registries are optional and may be injected by callers. Only
        # report non-sensitive provenance when the registry can describe it.
        rules = getattr(self.planner, "rules", None)
        provenance = getattr(rules, "provenance", None)
        if callable(provenance):
            provenance = provenance()
        if isinstance(provenance, dict):
            # Rule registries can carry caller policy data. Keep catalog
            # identity and published pack hashes, but never copy the policy.
            metadata["rules_provenance"] = _json_safe({
                key: value for key, value in provenance.items()
                if key in {"catalog_version", "packs"}
            })
        describe_year = getattr(rules, "describe_year", None)
        if callable(describe_year) and effective_years:
            metadata.setdefault("rules_provenance", {})["effective_years"] = {
                str(year): _summarize_rules_year(
                    describe_year(year, fallback_inflation=fallback_inflation),
                    fallback_inflation=fallback_inflation,
                )
                for year in effective_years
            }

        if method == "historical":
            metadata["historical_data"] = {
                "dataset_id": "sp500_annual_total_return",
                "vintage": {
                    "start_year": int(HISTORICAL_YEARS[0]),
                    "end_year": int(HISTORICAL_YEARS[-1]),
                },
                "distinct_start_count": len(HISTORICAL_YEARS),
                "sampled_start_indices": historical_start_indices,
                "wrapping": "cyclic; sequences continue from the first year after the final year",
            }
        return metadata

    @staticmethod
    def _get_return_sequence(start_year_index: int, num_years: int) -> List[float]:
        """Get a cyclically-wrapped sequence of historical returns."""
        span = len(_HISTORICAL_SNP500_VALUES)
        cycled = cycle(_HISTORICAL_SNP500_VALUES)
        for _ in range(start_year_index):
            next(cycled)
        return list(islice(cycled, num_years))


def _json_safe(value):
    """Convert optional provenance values to deterministic JSON data."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "value"):
        return _json_safe(value.value)
    return str(value)


def _summarize_rules_year(
    description: Dict, *, fallback_inflation: float,
) -> Dict:
    """Keep year-level rule lineage while omitting user policy payloads."""
    tax = description.get("tax", {}) if isinstance(description, dict) else {}
    contributions = (
        description.get("contributions", {})
        if isinstance(description, dict) else {}
    )
    summary = {
        "year": description.get("year"),
        "fallback_inflation": float(fallback_inflation),
        "policy_scenario": description.get("policy"),
        "tax": {
            key: tax[key] for key in ("status", "base_year", "source", "name")
            if key in tax
        },
        "contributions": {
            key: contributions[key]
            for key in ("status", "base_year") if key in contributions
        },
    }
    if "applied_change_ids" in description:
        summary["applied_change_count"] = len(description["applied_change_ids"])
    return _json_safe(summary)

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
