"""Tests for the first CLI redesign commands."""
import json
from click.testing import CliRunner
from retirement_planner.cli import main


def test_init_validate_inspect_project_explain():
    runner = CliRunner()
    with runner.isolated_filesystem():
        init_result = runner.invoke(main, ["init", "--output", "plan.json"])
        assert init_result.exit_code == 0, init_result.output

        validate_result = runner.invoke(main, ["validate", "--config", "plan.json"])
        assert validate_result.exit_code == 0, validate_result.output
        assert "valid" in validate_result.output.lower()

        inspect_result = runner.invoke(main, ["inspect", "--config", "plan.json", "--format", "json"])
        assert inspect_result.exit_code == 0, inspect_result.output
        assert json.loads(inspect_result.output)["monetary_convention"] == "real"

        project_result = runner.invoke(main, ["project", "--config", "plan.json", "--format", "json"])
        assert project_result.exit_code == 0, project_result.output
        assert isinstance(json.loads(project_result.output), list)

        explain_result = runner.invoke(main, ["explain", "--config", "plan.json", "--year", "2026"])
        assert explain_result.exit_code == 0, explain_result.output
        assert "Year 2026" in explain_result.output


def test_init_refuses_overwrite():
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(main, ["init", "--output", "plan.json"]).exit_code == 0
        result = runner.invoke(main, ["init", "--output", "plan.json"])
        assert result.exit_code != 0
        assert "overwrite" in result.output.lower()
