"""Tests for the Mantissa CLI interface."""
from click.testing import CliRunner
from retirement_planner.cli import main


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "Mantissa" in result.output or "retirement" in result.output.lower()


def test_run_requires_config():
    runner = CliRunner()
    result = runner.invoke(main, ["run"])
    assert result.exit_code != 0


def test_run_with_sample_config():
    runner = CliRunner()
    result = runner.invoke(main, [
        "run", "--config", "examples/sample_config.json", "--simulations", "10",
    ])
    assert result.exit_code == 0
    assert "Success Rate" in result.output or "success_rate" in result.output


def test_report_command():
    runner = CliRunner()
    result = runner.invoke(main, [
        "report", "--config", "examples/sample_config.json", "--format", "markdown",
    ])
    assert result.exit_code == 0


def test_report_show_equity_with_equity_config():
    """--show-equity flag outputs equity breakdown."""
    runner = CliRunner()
    result = runner.invoke(main, [
        "report", "--config", "tests/fixtures/equity_config.json",
        "--format", "markdown", "--show-equity",
    ])
    assert result.exit_code == 0
    assert "EXMP" in result.output
    assert "Equity:" in result.output


def test_report_show_equity_no_equity_config():
    """--show-equity flag on config without equity produces no extra output."""
    runner = CliRunner()
    result = runner.invoke(main, [
        "report", "--config", "examples/sample_config.json",
        "--format", "markdown", "--show-equity",
    ])
    assert result.exit_code == 0
    # No equity section should appear
    assert "EXMP" not in result.output
