"""Tests for configuration contracts and the projection state boundary."""
import json
from datetime import date

from click.testing import CliRunner

from retirement_planner.cli import main
from retirement_planner.config.validation import schema_dict, validate_config
from retirement_planner.projection.state import SimulationState


def valid_config():
    return {
        "schema_version": 1,
        "primary": {"name": "A", "birth_date": "1970-01-01", "retirement_date": "2035-01-01"},
        "spouse": {"name": "B", "birth_date": "1972-01-01", "retirement_date": "2035-01-01"},
        "accounts": [{"id": "a", "name": "Brokerage", "type": "brokerage", "balance": 1000}],
    }


def test_validation_reports_paths_duplicates_and_unknown_keys():
    config = valid_config()
    config["unexpected"] = True
    config["accounts"].append({"id": "a", "name": "Other", "type": "brokerage", "balance": -1})
    result = validate_config(config)
    assert not result.valid
    assert any(i.code == "duplicate" and "accounts[1].id" in i.path for i in result.errors)
    assert any(i.code == "range" for i in result.errors)
    assert any(i.code == "unknown_key" for i in result.warnings)
    assert validate_config(config, strict=True).errors


def test_schema_export_is_versioned():
    schema = schema_dict()
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["schema_version"]["const"] == 1


def test_simulation_state_tracks_totals_and_serializes():
    state = SimulationState(
        year=2035, primary_age=65, spouse_age=63,
        balances={"brokerage": 100, "roth": 50},
        liabilities={"mortgage": -25}, taxes=10,
    )
    assert state.total_assets() == 150
    assert state.total_liabilities() == 25
    assert state.net_worth() == 125
    state.add_warning("approximation")
    assert state.as_dict()["net_worth"] == 125


def test_cli_schema_and_validate():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("plan.json", "w") as handle:
            json.dump(valid_config(), handle)
        schema_result = runner.invoke(main, ["schema"])
        assert schema_result.exit_code == 0
        assert '"schema_version"' in schema_result.output
        validate_result = runner.invoke(main, ["validate", "--config", "plan.json"])
        assert validate_result.exit_code == 0, validate_result.output
        assert "valid" in validate_result.output.lower()
