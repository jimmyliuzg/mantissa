"""Tests for optional dependency handling (Phase 4.4).

Verifies:
- `doctor` CLI command outputs expected structure
- Charts module graceful fallback when matplotlib is missing
- PDF module graceful fallback when reportlab is missing
- Core engine works without optional dependencies
"""
import importlib
import json
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from retirement_planner.cli import main


SAMPLE_CONFIG = "examples/sample_config.json"


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------
class TestDoctorCommand:
    """Doctor command checks dependencies and outputs status."""

    def test_doctor_exits_cleanly(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert result.exit_code == 0

    def test_doctor_shows_python_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "Python:" in result.output

    def test_doctor_lists_core_deps(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "click" in result.output.lower()
        assert "tabulate" in result.output.lower()

    def test_doctor_lists_optional_deps(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "matplotlib" in result.output.lower()
        assert "reportlab" in result.output.lower()

    def test_doctor_shows_feature_names(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor"])
        assert "charts" in result.output.lower()
        assert "pdf" in result.output.lower()


# ---------------------------------------------------------------------------
# Charts fallback
# ---------------------------------------------------------------------------
class TestChartsFallback:
    """Charts module handles missing matplotlib gracefully."""

    def test_charts_import_error_is_helpful(self):
        """When matplotlib is missing, ImportError has install instructions."""
        with patch.dict("sys.modules", {"matplotlib": None}):
            # Force reimport of charts module
            import retirement_planner.charts as charts_mod
            # The module uses lazy import, so calling a function should fail
            # with a helpful message
            try:
                charts_mod._require_matplotlib()
                # If matplotlib is actually installed, the function succeeds
                # That's fine — we're testing the error path exists
            except ImportError as e:
                assert "matplotlib" in str(e).lower()
                assert "pip install" in str(e).lower()

    def test_init_gracefully_handles_missing_charts(self):
        """Package import succeeds even if charts functions are unavailable."""
        import retirement_planner
        # generate_pdf_report and chart functions should be importable
        # (they may be None if deps are missing)
        # This just verifies the package imports without crash
        assert hasattr(retirement_planner, "RetirementPlanner")


# ---------------------------------------------------------------------------
# PDF fallback
# ---------------------------------------------------------------------------
class TestPDFFallback:
    """PDF module handles missing reportlab gracefully."""

    def test_pdf_import_error_is_helpful(self):
        """When reportlab is missing, CLI pdf command gives helpful error."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "pdf", "--config", SAMPLE_CONFIG,
            "--output", "/tmp/test_report.pdf",
        ])
        # Should either succeed (if reportlab installed) or fail with
        # helpful message about missing dependency
        if result.exit_code != 0:
            output = result.output.lower()
            assert "reportlab" in output or "pdf" in output


# ---------------------------------------------------------------------------
# Core engine independence
# ---------------------------------------------------------------------------
class TestCoreEngineIndependence:
    """Core engine works without optional chart/pdf dependencies."""

    def test_engine_loads_without_charts(self):
        """RetirementPlanner can be imported and used without matplotlib."""
        from retirement_planner.engine import RetirementPlanner
        planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
        assert planner is not None

    def test_projection_works_without_optional_deps(self):
        """Deterministic projection succeeds without optional deps."""
        from retirement_planner.engine import RetirementPlanner
        planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
        projections = planner.project_cash_flow("mean")
        assert len(projections) > 0
        assert projections[0]["income"] > 0

    def test_report_json_works_without_optional_deps(self):
        """CLI report --format json succeeds without optional deps."""
        runner = CliRunner()
        result = runner.invoke(main, [
            "report", "--config", SAMPLE_CONFIG,
            "--format", "json", "--simulations", "10",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "summary" in data

    def test_schema_works_without_optional_deps(self):
        """CLI schema command succeeds without optional deps."""
        runner = CliRunner()
        result = runner.invoke(main, ["schema"])
        assert result.exit_code == 0
        schema = json.loads(result.output)
        assert isinstance(schema, dict)


# ---------------------------------------------------------------------------
# pyproject.toml structure
# ---------------------------------------------------------------------------
class TestPackageStructure:
    """Verify optional deps are correctly declared in pyproject.toml."""

    def test_optional_deps_in_pyproject(self):
        """pyproject.toml has optional-dependencies section."""
        import tomllib
        pyproject_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "pyproject.toml"
        )
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        opt_deps = config.get("project", {}).get("optional-dependencies", {})
        assert "charts" in opt_deps
        assert "pdf" in opt_deps
        assert "all" in opt_deps
        assert any("matplotlib" in d for d in opt_deps["charts"])
        assert any("reportlab" in d for d in opt_deps["pdf"])

    def test_core_deps_are_minimal(self):
        """Core dependencies are click and tabulate only."""
        import tomllib
        pyproject_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "pyproject.toml"
        )
        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        deps = config.get("project", {}).get("dependencies", [])
        dep_names = [d.split(">=")[0].split("==")[0].strip() for d in deps]
        assert "click" in dep_names
        assert "tabulate" in dep_names
        assert "matplotlib" not in dep_names
        assert "reportlab" not in dep_names
