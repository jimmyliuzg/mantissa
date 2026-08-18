import os, tempfile

import pytest

pytest.importorskip("matplotlib", reason="chart tests require the optional charts extra")

from retirement_planner.charts import (
    plot_net_worth_trajectory, plot_mc_fan_chart,
    plot_income_vs_expenses, plot_tax_breakdown,
)

def test_net_worth_trajectory_creates_file():
    cash_flow = [
        {"year": 2024, "net_worth": 500_000},
        {"year": 2025, "net_worth": 550_000},
        {"year": 2026, "net_worth": 600_000},
    ]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        plot_net_worth_trajectory(cash_flow, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)

def test_mc_fan_chart_creates_file():
    mc_results = {
        "percentiles": [
            {"label": "p10", "value": 800_000},
            {"label": "p25", "value": 1_500_000},
            {"label": "p50 (median)", "value": 2_500_000},
            {"label": "p75", "value": 3_500_000},
            {"label": "p90", "value": 4_200_000},
        ],
    }
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        plot_mc_fan_chart(mc_results, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)

def test_income_vs_expenses_creates_file():
    cash_flow = [
        {"year": 2024, "income": 120_000, "expenses": 80_000},
        {"year": 2025, "income": 123_600, "expenses": 82_000},
    ]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        plot_income_vs_expenses(cash_flow, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)

def test_tax_breakdown_creates_file():
    cash_flow = [
        {"year": 2024, "taxes": 15_000},
        {"year": 2025, "taxes": 16_000},
    ]
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        plot_tax_breakdown(cash_flow, path)
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
    finally:
        os.unlink(path)
