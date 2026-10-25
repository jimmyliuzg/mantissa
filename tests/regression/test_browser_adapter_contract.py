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
