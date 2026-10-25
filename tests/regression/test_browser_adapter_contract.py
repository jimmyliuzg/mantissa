"""Exercise the browser's embedded Python against the actual native engine."""
import ast
import json
from pathlib import Path


def test_browser_result_preserves_model_warnings():
    source = (Path(__file__).resolve().parents[2] / "web/src/engine/pyodide.ts").read_text()
    code = source.split("    const code = `", 1)[1].split("\n`;", 1)[0]
    config = {
        "start_year": 2026, "balance_date": "2026-10-01",
        "primary": {"name": "A", "birth_date": "1990-01-01",
                    "retirement_date": "2026-01-01", "longevity_age": 37},
        "accounts": [{"id": "brokerage", "name": "Brokerage", "type": "brokerage",
                      "tax_treatment": "taxable", "balance": 100_000}],
        "expenses": [],
    }
    namespace = {"MANTISSA_CONFIG": config, "MANTISSA_SIMS": 1,
                 "MANTISSA_METHOD": "gaussian", "MANTISSA_SEED": 42}
    program = ast.parse(code)
    # The last expression is the JSON returned by Pyodide.
    last = program.body.pop()
    exec(compile(program, "browser-adapter", "exec"), namespace)
    result = json.loads(eval(compile(ast.Expression(last.value), "browser-result", "eval"), namespace))
    messages = [w["message"] for w in result["warnings"]]
    assert any("cost_basis" in message for message in messages)
    assert any("Whole-year" in message for message in messages)
    assert any("Access policy" in message for message in messages)
    assert len(messages) == len(set(messages))
    assert all(w["severity"] == "warning" and w["year"] is None for w in result["warnings"])
    assert "accessFailureRate" in result["kpis"]
    assert "portfolioDepletionRate" in result["kpis"]
    assert all("accessShortfall" in row for row in result["cashFlow"])


def test_total_only_browser_result_does_not_imply_account_access_validation():
    source = (Path(__file__).resolve().parents[2] / "web/src/engine/pyodide.ts").read_text()
    code = source.split("    const code = `", 1)[1].split("\n`;", 1)[0]
    config = json.loads((Path(__file__).parents[1] / "fixtures/wizard-contract.json").read_text())[0]['config']
    namespace = {"MANTISSA_CONFIG": config, "MANTISSA_SIMS": 1,
                 "MANTISSA_METHOD": "gaussian", "MANTISSA_SEED": 42}
    program = ast.parse(code)
    last = program.body.pop()
    exec(compile(program, "browser-adapter", "exec"), namespace)
    result = json.loads(eval(compile(ast.Expression(last.value), "browser-result", "eval"), namespace))
    assert result['kpis']['provisional'] is True
    assert result['kpis']['accessAssessed'] is False
    assert 'accessFailureRate' not in result['kpis']
    assert result['inputReadiness']['access_assessed'] is False
    assert result['kpis']['spendingCutFrequency'] == 0
    assert all(row['accessibleSpendingBalance'] is None for row in result['cashFlow'])


def test_browser_outcomes_match_native_engine_and_keep_unassessed_access_null():
    from retirement_planner import RetirementPlanner, MonteCarloEngine
    from tempfile import NamedTemporaryFile
    source = (Path(__file__).resolve().parents[2] / "web/src/engine/pyodide.ts").read_text()
    code = source.split("    const code = `", 1)[1].split("\n`;", 1)[0]
    config={"start_year":2030,"primary":{"name":"Example","birth_date":"1990-01-01","retirement_date":"2030-01-01","longevity_age":40},
            "accounts":[{"id":"cash","name":"Cash","type":"checking","balance":100_000,"growth_rate":0}],
            "withdrawal_access_policy":"unrestricted","legacy_goal":200_000}
    namespace={"MANTISSA_CONFIG":config,"MANTISSA_SIMS":1,"MANTISSA_METHOD":"gaussian","MANTISSA_SEED":42}
    program=ast.parse(code);last=program.body.pop()
    exec(compile(program,"browser-adapter","exec"),namespace)
    browser=json.loads(eval(compile(ast.Expression(last.value),"browser-result","eval"),namespace))
    with NamedTemporaryFile(mode='w',suffix='.json') as f:
        json.dump(config,f);f.flush()
        planner=RetirementPlanner.from_config(f.name)
    native=MonteCarloEngine(planner).run(num_simulations=1,seed=42)
    assert browser['outcomes'] == native['outcomes']
    assert browser['outcomes']['planned_spending_met_rate'] == 1
    assert browser['outcomes']['legacy_target_met_rate'] == 0
    assert browser['outcomes']['account_access_met_rate'] is None
    assert browser['kpis']['accessAssessed'] is False
    assert browser['cashFlow'][0]['accountAccessMet'] is None
    assert browser['cashFlow'][0]['fundingShortfall'] == 0
