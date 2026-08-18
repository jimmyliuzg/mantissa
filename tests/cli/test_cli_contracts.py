"""Golden CLI contract tests (Phase 4.3).

Verify that CLI commands produce structurally correct, parseable output
with expected fields and exit codes. These serve as regression guards
for the CLI's public API.
"""
import json
import os
import tempfile

import pytest
from click.testing import CliRunner

from retirement_planner.cli import main


SAMPLE_CONFIG = "examples/sample_config.json"
FIXTURES = "tests/fixtures"


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Shared contracts
# ---------------------------------------------------------------------------
class TestCLIBasicContracts:
    """Version, help, and error handling."""

    def test_version_output(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output

    def test_changelog_matches_package_version(self):
        import re
        from retirement_planner import __version__

        with open("CHANGELOG.md", encoding="utf-8") as changelog:
            first_release = re.search(r"^## \[([^\]]+)\]", changelog.read(), re.MULTILINE)
        assert first_release is not None
        assert first_release.group(1) == __version__

    def test_help_lists_commands(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        output = result.output.lower()
        for cmd in ["report", "run", "validate", "schema", "project", "explain"]:
            assert cmd in output, f"Command '{cmd}' not listed in help"

    def test_run_requires_config(self, runner):
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0

    def test_report_requires_config(self, runner):
        result = runner.invoke(main, ["report"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Validate command
# ---------------------------------------------------------------------------
class TestValidateContract:
    """Validate command returns structured output."""

    def test_validate_sample_config(self, runner):
        result = runner.invoke(main, ["validate", "--config", SAMPLE_CONFIG])
        assert result.exit_code == 0

    def test_validate_invalid_config(self, runner):
        result = runner.invoke(main, ["validate", "--config", "/nonexistent.json"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Schema command
# ---------------------------------------------------------------------------
class TestSchemaContract:
    """Schema command outputs valid JSON."""

    def test_schema_outputs_json(self, runner):
        result = runner.invoke(main, ["schema"])
        assert result.exit_code == 0
        # Should be valid JSON
        schema = json.loads(result.output)
        assert isinstance(schema, dict)

    def test_schema_has_properties(self, runner):
        result = runner.invoke(main, ["schema"])
        schema = json.loads(result.output)
        # Schema should define some properties
        assert "properties" in schema or "$schema" in schema or "type" in schema


# ---------------------------------------------------------------------------
# Report command — JSON output
# ---------------------------------------------------------------------------
class TestReportJSONContract:
    """Report --format json must produce valid JSON with expected structure."""

    def test_report_json_valid(self, runner):
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "json", "--simulations", "10",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_report_json_has_sections(self, runner):
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "json", "--simulations", "10",
        ])
        data = json.loads(result.output)
        assert "summary" in data
        assert "cash_flow" in data
        assert "monte_carlo" in data

    def test_report_json_summary_fields(self, runner):
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "json", "--simulations", "10",
        ])
        data = json.loads(result.output)
        summary = data["summary"]
        # Summary should have key metrics
        assert isinstance(summary, dict)
        # Should have some numeric fields
        numeric_fields = [k for k, v in summary.items() if isinstance(v, (int, float))]
        assert len(numeric_fields) > 0, "Summary has no numeric fields"

    def test_report_json_cash_flow_has_rows(self, runner):
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "json", "--simulations", "10",
        ])
        data = json.loads(result.output)
        cf = data["cash_flow"]
        assert isinstance(cf, dict)
        assert "rows" in cf
        assert len(cf["rows"]) > 0

    def test_report_json_cash_flow_row_schema(self, runner):
        """Each cash flow row must have year, income, expenses, taxes."""
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "json", "--simulations", "10",
        ])
        data = json.loads(result.output)
        for row in data["cash_flow"]["rows"]:
            assert "year" in row
            assert "income" in row
            assert "expenses" in row
            assert "taxes" in row
            assert isinstance(row["year"], int)
            assert isinstance(row["income"], (int, float))

    def test_report_writes_to_file(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            result = runner.invoke(main, [
                "report", "--config", SAMPLE_CONFIG,
                "--format", "json", "--simulations", "10",
                "--output", path,
            ])
            assert result.exit_code == 0
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert "summary" in data
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Report command — CSV output
# ---------------------------------------------------------------------------
class TestReportCSVContract:
    """Report --format csv must produce valid CSV with header row."""

    def test_report_csv_has_header(self, runner):
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "csv", "--simulations", "10",
        ])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) > 1, "CSV has no data rows"
        header = lines[0]
        assert "year" in header.lower() or "Year" in header


# ---------------------------------------------------------------------------
# Report command — Markdown output
# ---------------------------------------------------------------------------
class TestReportMarkdownContract:
    """Report --format markdown must produce non-empty markdown."""

    def test_report_markdown_nonempty(self, runner):
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "markdown", "--simulations", "10",
        ])
        assert result.exit_code == 0
        assert len(result.output) > 100, "Markdown output suspiciously short"


# ---------------------------------------------------------------------------
# Run command
# ---------------------------------------------------------------------------
class TestRunContract:
    """Run command executes Monte Carlo and produces output."""

    def test_run_sample_config(self, runner):
        result = runner.invoke(main, [
            "run", "--config", SAMPLE_CONFIG,
            "--simulations", "10",
        ])
        assert result.exit_code == 0

    def test_run_writes_output(self, runner):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            result = runner.invoke(main, [
                "run", "--config", SAMPLE_CONFIG,
                "--simulations", "10", "--output", path,
            ])
            assert result.exit_code == 0
            assert os.path.exists(path)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Project command
# ---------------------------------------------------------------------------
class TestProjectContract:
    """Project command outputs deterministic projection."""

    def test_project_json_valid(self, runner):
        result = runner.invoke(main, [
            "project", "--config", SAMPLE_CONFIG,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_project_row_schema(self, runner):
        result = runner.invoke(main, [
            "project", "--config", SAMPLE_CONFIG,
            "--format", "json",
        ])
        data = json.loads(result.output)
        for row in data[:5]:  # Check first 5 rows
            assert "year" in row
            assert "income" in row
            assert "net_worth" in row


# ---------------------------------------------------------------------------
# Inspect command
# ---------------------------------------------------------------------------
class TestInspectContract:
    """Inspect command shows config summary."""

    def test_inspect_json_valid(self, runner):
        result = runner.invoke(main, [
            "inspect", "--config", SAMPLE_CONFIG,
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)
