"""Tests for PDF report generation."""
import os
from pathlib import Path

from retirement_planner.engine import RetirementPlanner
from retirement_planner.simulators import MonteCarloEngine
from retirement_planner.pdf_report import generate_pdf_report, _fmt_money, _fmt_pct


SAMPLE_CONFIG = "examples/sample_config.json"


def test_pdf_report_creates_file(tmp_path):
    """PDF report creates a valid file."""
    planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
    mc = MonteCarloEngine(planner)
    cash_flow = planner.project_cash_flow()
    mc_results = mc.run(num_simulations=10, scenario="mean")

    out = tmp_path / "report.pdf"
    result = generate_pdf_report(planner, mc_results, cash_flow, str(out))

    assert os.path.exists(result)
    assert os.path.getsize(result) > 1000  # Non-trivial size


def test_pdf_report_starts_with_header(tmp_path):
    """PDF file starts with %PDF header."""
    planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
    mc = MonteCarloEngine(planner)
    cash_flow = planner.project_cash_flow()
    mc_results = mc.run(num_simulations=10, scenario="mean")

    out = tmp_path / "report.pdf"
    result = generate_pdf_report(planner, mc_results, cash_flow, str(out))

    with open(result, "rb") as f:
        header = f.read(5)
    assert header == b"%PDF-"


def test_pdf_report_has_multiple_pages(tmp_path):
    """Report has multiple pages (cover + content)."""
    planner = RetirementPlanner.from_config(SAMPLE_CONFIG)
    mc = MonteCarloEngine(planner)
    cash_flow = planner.project_cash_flow()
    mc_results = mc.run(num_simulations=10, scenario="mean")

    out = tmp_path / "report.pdf"
    result = generate_pdf_report(planner, mc_results, cash_flow, str(out))

    with open(result, "rb") as f:
        content = f.read()
    # Count page objects (approximate)
    pages = content.count(b"/Type /Page") - content.count(b"/Type /Pages")
    assert pages >= 5  # Cover + summary + net worth + income + MC + assumptions + appendix


def test_fmt_money():
    """Money formatting works correctly."""
    assert _fmt_money(1_500_000) == "$1.5M"
    assert _fmt_money(2_000_000) == "$2.0M"
    assert _fmt_money(500_000) == "$500,000"
    assert _fmt_money(0) == "$0"


def test_fmt_pct():
    """Percentage formatting works correctly."""
    assert _fmt_pct(0.85) == "85.0%"
    assert _fmt_pct(0.0) == "0.0%"
    assert _fmt_pct(1.0) == "100.0%"
