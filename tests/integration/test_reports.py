import json, csv, os, tempfile
from retirement_planner.reports import (
    generate_summary_report, generate_cash_flow_report,
    generate_mc_report, export_json, export_csv, export_markdown,
)

def test_summary_report_contains_keys():
    mc_results = {
        "success_rate": 0.85, "median_final_nw": 2_500_000,
        "p10_final_nw": 800_000, "p90_final_nw": 4_200_000,
        "median_taxes": 450_000, "out_of_savings_rate": 0.05,
        "num_simulations": 1000, "scenario": "mean",
    }
    cash_flow = [
        {"year": 2024, "income": 120_000, "expenses": 80_000,
         "taxes": 15_000, "net_worth": 500_000, "net_cash_flow": 25_000},
    ]
    report = generate_summary_report(mc_results, cash_flow)
    assert "success_rate" in report
    assert "final_net_worth_median" in report
    assert "years_of_data" in report

def test_cash_flow_report_rows():
    cash_flow = [
        {"year": 2024, "income": 120_000, "expenses": 80_000,
         "taxes": 15_000, "net_worth": 500_000, "net_cash_flow": 25_000,
         "income_by_source": {"Salary": 120_000},
         "expenses_by_category": {"Housing": 30_000, "Food": 20_000}},
        {"year": 2025, "income": 123_600, "expenses": 82_000,
         "taxes": 16_000, "net_worth": 550_000, "net_cash_flow": 25_600,
         "income_by_source": {"Salary": 123_600},
         "expenses_by_category": {"Housing": 31_000, "Food": 21_000}},
    ]
    report = generate_cash_flow_report(cash_flow)
    assert len(report["rows"]) == 2
    assert report["rows"][0]["year"] == 2024

def test_mc_report_percentiles():
    mc_results = {
        "success_rate": 0.85, "median_final_nw": 2_500_000,
        "p10_final_nw": 800_000, "p25_final_nw": 1_500_000,
        "p75_final_nw": 3_500_000, "p90_final_nw": 4_200_000,
        "median_peak_nw": 3_000_000, "median_taxes": 450_000,
        "out_of_savings_rate": 0.05, "num_simulations": 1000,
        "scenario": "mean", "method": "gaussian",
    }
    report = generate_mc_report(mc_results)
    assert "success_rate" in report
    assert "percentiles" in report
    assert len(report["percentiles"]) == 5

def test_export_json(tmp_path):
    data = {"key": "value", "number": 42}
    out = tmp_path / "report.json"
    export_json(data, str(out))
    assert out.exists()
    with open(out) as f:
        loaded = json.load(f)
    assert loaded == data

def test_export_csv(tmp_path):
    rows = [
        {"year": 2024, "income": 120000, "expenses": 80000},
        {"year": 2025, "income": 123600, "expenses": 82000},
    ]
    out = tmp_path / "report.csv"
    export_csv(rows, str(out))
    assert out.exists()
    with open(out) as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        data_rows = list(reader)
    assert "year" in headers
    assert len(data_rows) == 2

def test_export_markdown():
    rows = [{"year": 2024, "income": 120000, "expenses": 80000}]
    md = export_markdown(rows, title="Cash Flow")
    assert "# Cash Flow" in md
    assert "| year |" in md
    assert "| 2024 |" in md
