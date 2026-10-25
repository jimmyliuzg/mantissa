"""Reproducibility contracts for Monte Carlo runs."""
from datetime import date
import json
import random

import numpy as np
import pytest

from retirement_planner import RetirementPlanner
from retirement_planner.models import (
    Account, EconomicAssumptions, Expense, Person, Scenario, SocialSecurity,
)
from retirement_planner.simulators import MonteCarloEngine


def _planner(policy=None):
    scenario = Scenario(
        name="repro",
        description="",
        state="CA",
        primary=Person(
            name="P", birth_date=date(1960, 1, 1),
            retirement_date=date(2025, 1, 1), longevity_age=78,
        ),
        spouse=None,
        policy=policy,
        economic=EconomicAssumptions(),
        accounts=[Account("b", "B", "brokerage", "taxable", 1_000_000,
                          growth_rate=0.0, equity_pct=0.6)],
        income_streams=[],
        expenses=[Expense(
            id="living", name="living", monthly_amount=2_000,
            start_date=date(2025, 1, 1), end_date=date(2100, 1, 1),
            is_must_spend=True,
        )],
        mortgages=[],
        social_security=SocialSecurity(primary_benefit_at_67=1_000),
        dependents=[],
    )
    return RetirementPlanner(scenario)


@pytest.mark.parametrize("method", ["gaussian", "historical"])
@pytest.mark.parametrize("stochastic", [False, True])
def test_seed_repeats_full_pipeline(method, stochastic):
    engine = MonteCarloEngine(_planner())
    first = engine.run(num_simulations=2, method=method, seed=191,
                       stochastic=stochastic)
    second = engine.run(num_simulations=2, method=method, seed=191,
                        stochastic=stochastic)
    assert first == second
    assert first["run_metadata"]["effective_seed"] == 191


def test_unseeded_run_can_be_replayed_from_metadata():
    engine = MonteCarloEngine(_planner(policy={
        "schema_version": 1,
        "tax_threshold_growth_rate": 0.03,
        "changes": [],
    }))
    first = engine.run(num_simulations=2, method="historical", stochastic=True,
                       scenario="optimistic", stress_level=0.2)
    assert 0 <= first["run_metadata"]["effective_seed"] <= 2**53 - 1
    replay = engine.run(
        num_simulations=2, method="historical", stochastic=True,
        seed=first["run_metadata"]["effective_seed"],
        scenario="optimistic", stress_level=0.2,
    )
    assert first == replay


def test_max_safe_seed_survives_json_round_trip_and_replays():
    max_safe_seed = 2**53 - 1
    engine = MonteCarloEngine(_planner())
    first = engine.run(num_simulations=1, seed=max_safe_seed)
    returned_seed = json.loads(json.dumps(
        first["run_metadata"]))["effective_seed"]
    assert returned_seed == max_safe_seed
    assert engine.run(num_simulations=1, seed=returned_seed) == first


@pytest.mark.parametrize("method", ["gaussian", "historical"])
def test_metadata_is_stable_and_json_safe(method):
    engine = MonteCarloEngine(_planner())
    a = engine.run(num_simulations=1, method=method, seed=7)
    b = engine.run(num_simulations=1, method=method, seed=7)
    assert a["run_metadata"] == b["run_metadata"]
    assert a["run_metadata"]["schema_version"] == 1
    assert a["run_metadata"]["model_version"]
    assert a["run_metadata"]["simulations"] == 1
    assert a["run_metadata"]["mortality_mode"] == "deterministic"
    json.dumps(a["run_metadata"])
    if method == "historical":
        history = a["run_metadata"]["historical_data"]
        assert history["distinct_start_count"] > 0
        assert history["vintage"]["start_year"] < history["vintage"]["end_year"]
        assert len(history["sampled_start_indices"]) == 1
        assert 0 <= history["sampled_start_indices"][0] < history["distinct_start_count"]
        assert "cyclic" in history["wrapping"]
    else:
        assert "historical_data" not in a["run_metadata"]


def test_metadata_uses_fingerprint_and_summarized_rule_provenance_only():
    policy = {
        "schema_version": 1,
        "tax_threshold_growth_rate": 0.03,
        "changes": [{
            "id": "private-change-id",
            "start_year": 2025,
            "end_year": 2099,
            "tax": {"federal_rate_addition": 0.0},
            "contributions": {"ira_limit": 123456},
        }],
    }
    planner = _planner(policy=policy)
    result = MonteCarloEngine(planner).run(
        num_simulations=1, seed=31, scenario="optimistic")
    metadata = result["run_metadata"]
    serialized = json.dumps(metadata)
    assert metadata["config_fingerprint"] == planner.config_fingerprint()
    assert len(metadata["config_fingerprint"]) == 64
    assert metadata["fingerprint_kind"] == "resolved_scenario"
    assert metadata["rules_provenance"]["catalog_version"]
    assert "private_amount" not in serialized
    assert "private-change-id" not in serialized
    assert "123456" not in serialized
    assert metadata["rules_provenance"]["effective_years"]
    sample = next(iter(metadata["rules_provenance"]["effective_years"].values()))
    assert sample["fallback_inflation"] == pytest.approx(
        planner.scenario.economic.get_rate("optimistic")["general_inflation"])
    assert sample["fallback_inflation"] != 0.025
    assert sample["applied_change_count"] == 1


def test_policy_fingerprints_are_stable_and_distinguish_forecasts():
    first_policy = {"schema_version": 1, "tax_threshold_growth_rate": 0.03,
                    "changes": []}
    same_policy = {"schema_version": 1, "tax_threshold_growth_rate": 0.03,
                   "changes": []}
    changed_policy = {"schema_version": 1, "tax_threshold_growth_rate": 0.04,
                      "changes": []}
    a = MonteCarloEngine(_planner(first_policy)).run(num_simulations=1, seed=3)
    b = MonteCarloEngine(_planner(same_policy)).run(num_simulations=1, seed=3)
    c = MonteCarloEngine(_planner(changed_policy)).run(num_simulations=1, seed=3)
    assert a["run_metadata"]["config_fingerprint"] == b["run_metadata"]["config_fingerprint"]
    assert a["run_metadata"]["config_fingerprint"] != c["run_metadata"]["config_fingerprint"]


def test_simulation_does_not_change_module_global_random_states():
    python_state = random.getstate()
    numpy_state = np.random.get_state()
    MonteCarloEngine(_planner()).run(
        num_simulations=2, method="historical", seed=19, stochastic=True)
    assert random.getstate() == python_state
    after = np.random.get_state()
    assert after[0] == numpy_state[0]
    assert np.array_equal(after[1], numpy_state[1])
    assert after[2:] == numpy_state[2:]


def test_mc_aggregates_run_level_model_warnings():
    planner = _planner()
    original = planner.run_single_simulation
    contribution_warning = "Automatic IRA contribution was skipped during the annual path."

    def run_with_warning(*args, **kwargs):
        result = original(*args, **kwargs)
        result["model_warnings"].append(contribution_warning)
        return result

    planner.run_single_simulation = run_with_warning
    result = MonteCarloEngine(planner).run(num_simulations=2, seed=11)
    assert result["model_warnings"].count(contribution_warning) == 1
    assert set(planner.model_warnings).issubset(result["model_warnings"])


@pytest.mark.parametrize("kwargs", [
    {"method": "unsupported"},
    {"scenario": "unknown"},
    {"num_simulations": 0},
    {"return_volatility": -0.1},
    {"return_volatility": float("nan")},
    {"stress_level": -0.1},
    {"stress_level": 1.1},
    {"seed": -1},
])
def test_invalid_run_inputs_are_rejected(kwargs):
    with pytest.raises(ValueError):
        MonteCarloEngine(_planner()).run(**kwargs)


def test_seed_above_json_safe_range_is_rejected():
    with pytest.raises(ValueError, match=r"seed must be an integer between 0 and 9007199254740991"):
        MonteCarloEngine(_planner()).run(seed=2**53)
