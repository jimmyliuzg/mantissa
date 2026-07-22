"""Report generation and export for retirement planner output."""
from typing import Any, Dict, List
import csv
import json
from pathlib import Path


def generate_summary_report(mc_results: Dict[str, Any], cash_flow: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a high-level summary report from Monte Carlo results and cash flow data."""
    return {
        "success_rate": mc_results.get("success_rate", 0.0),
        "final_net_worth_median": mc_results.get("median_final_nw", 0.0),
        "final_net_worth_p10": mc_results.get("p10_final_nw", 0.0),
        "final_net_worth_p90": mc_results.get("p90_final_nw", 0.0),
        "median_taxes": mc_results.get("median_taxes", 0.0),
        "out_of_savings_rate": mc_results.get("out_of_savings_rate", 0.0),
        "num_simulations": mc_results.get("num_simulations", 0),
        "scenario": mc_results.get("scenario", "unknown"),
        "years_of_data": len(cash_flow),
    }


def generate_cash_flow_report(cash_flow: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a structured cash flow report with rows and column metadata."""
    columns = ["year", "income", "expenses", "taxes", "net_worth", "net_cash_flow"]
    return {
        "rows": cash_flow,
        "columns": columns,
    }


def generate_mc_report(mc_results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Monte Carlo analysis report with percentile breakdowns."""
    percentiles = []
    for pct in [10, 25, 50, 75, 90]:
        key = f"p{pct}_final_nw"
        percentiles.append({"percentile": pct, "value": mc_results.get(key, 0.0)})

    return {
        "success_rate": mc_results.get("success_rate", 0.0),
        "percentiles": percentiles,
        "median_peak_nw": mc_results.get("median_peak_nw", 0.0),
        "median_taxes": mc_results.get("median_taxes", 0.0),
        "out_of_savings_rate": mc_results.get("out_of_savings_rate", 0.0),
        "num_simulations": mc_results.get("num_simulations", 0),
        "scenario": mc_results.get("scenario", "unknown"),
        "method": mc_results.get("method", "unknown"),
    }


def generate_account_report(cash_flow: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Placeholder for account-level breakdown report."""
    return {"accounts": [], "cash_flow": cash_flow}


def export_json(data: Any, filepath: str) -> None:
    """Write data to a JSON file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)


def export_csv(rows: List[Dict[str, Any]], filepath: str) -> None:
    """Write a list of dicts to a CSV file."""
    if not rows:
        return
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def export_markdown(rows: List[Dict[str, Any]], title: str) -> str:
    """Generate a Markdown table string from a list of dicts."""
    if not rows:
        return f"# {title}\n\nNo data.\n"
    headers = list(rows[0].keys())
    lines = [f"# {title}\n", "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
    return "\n".join(lines) + "\n"
