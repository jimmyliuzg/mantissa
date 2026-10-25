"""Report generation and export for retirement planner output."""
from typing import Any, Dict, List
import csv
import json
from pathlib import Path


def generate_summary_report(mc_results: Dict[str, Any], cash_flow: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate a high-level summary report from Monte Carlo results and cash flow data."""
    return {
        "success_rate": mc_results.get("success_rate", 0.0),
        "outcomes": mc_results.get("outcomes"),
        "input_readiness": mc_results.get("input_readiness"),
        "spending_cut_frequency": mc_results.get("spending_cut_frequency"),
        "median_years_with_spending_cuts": mc_results.get("median_years_with_spending_cuts"),
        "maximum_spending_cut_fraction": mc_results.get("maximum_spending_cut_fraction"),
        "withdrawal_access_policy": mc_results.get("withdrawal_access_policy"),
        "access_failure_rate": mc_results.get("access_failure_rate"),
        "portfolio_depletion_rate": mc_results.get("portfolio_depletion_rate"),
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
    columns = ["year", "income", "planned_expenses", "expenses", "spending_cut", "funding_shortfall", "adjusted_spending_met", "planned_spending_met", "account_access_met", "taxes", "net_worth", "net_cash_flow"]
    return {
        "rows": cash_flow,
        "columns": columns,
    }


def generate_mc_report(mc_results: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a Monte Carlo analysis report with percentile breakdowns.

    Returns a dict.  Note: export_markdown() returns a str — this
    inconsistency is by design; *generate_* functions return structured
    data while *export_* functions produce serialized output.
    """
    percentiles = []
    for pct in [10, 25, 50, 75, 90]:
        key = f"p{pct}_final_nw"
        percentiles.append({"percentile": pct, "value": mc_results.get(key, 0.0)})

    return {
        "success_rate": mc_results.get("success_rate", 0.0),
        "outcomes": mc_results.get("outcomes"),
        "input_readiness": mc_results.get("input_readiness"),
        "spending_cut_frequency": mc_results.get("spending_cut_frequency"),
        "median_years_with_spending_cuts": mc_results.get("median_years_with_spending_cuts"),
        "maximum_spending_cut_fraction": mc_results.get("maximum_spending_cut_fraction"),
        "withdrawal_access_policy": mc_results.get("withdrawal_access_policy"),
        "access_failure_rate": mc_results.get("access_failure_rate"),
        "portfolio_depletion_rate": mc_results.get("portfolio_depletion_rate"),
        "percentiles": percentiles,
        "median_peak_nw": mc_results.get("median_peak_nw", 0.0),
        "median_taxes": mc_results.get("median_taxes", 0.0),
        "out_of_savings_rate": mc_results.get("out_of_savings_rate", 0.0),
        "num_simulations": mc_results.get("num_simulations", 0),
        "scenario": mc_results.get("scenario", "unknown"),
        "method": mc_results.get("method", "unknown"),
        "mortality_distribution": mc_results.get("mortality_distribution"),
    }


def export_json(data: Any, filepath: str) -> None:
    """Write data to a JSON file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, default=str)


def export_csv(rows: List[Dict[str, Any]], filepath: str) -> bool:
    """Write a list of dicts to a CSV file.

    Returns True if the file was written, False if rows was empty.
    """
    if not rows:
        import warnings
        warnings.warn("export_csv: no rows to write — skipping CSV export", stacklevel=2)
        return False
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


CAUSE_LABELS = {
    "account_access": "Account access",
    "unassessed_access": "Account access unassessed",
    "liquid_capital": "Spendable-capital shortfall",
    "housing_purchase": "Housing purchase funding",
    "funding_gap": "Combined funding gap",
}


def outcome_metric_rows(mc_results):
    """One human-readable outcome definition for CLI and exported reports."""
    outcomes = mc_results.get("outcomes")
    if not outcomes:
        return [("Combined Success Rate (legacy)", f"{mc_results.get('success_rate', 0):.1%}"),
                ("Separate outcomes", "Unavailable in this older result")]
    pct = lambda value: f"{value:.1%}" if value is not None else "Unassessed"
    rows = [
        ("Planned spending met without cuts", pct(outcomes["planned_spending_met_rate"])),
        ("Adjusted budget funded", pct(outcomes["adjusted_spending_met_rate"])),
        ("No account-access gaps", pct(outcomes["account_access_met_rate"])),
        ("After-estate legacy target met", pct(outcomes["legacy_target_met_rate"])),
        ("Legacy target (base-year dollars)", f"${outcomes['legacy_target_base_year']:,.0f}"),
        ("Combined Success Rate (legacy)", pct(mc_results.get("success_rate", 0))),
        ("Runs with spending cuts", pct(mc_results.get("spending_cut_frequency"))),
        ("Median years with spending cuts", str(mc_results.get("median_years_with_spending_cuts", 0))),
        ("Deepest annual budget cut", pct(mc_results.get("maximum_spending_cut_fraction"))),
    ]
    rows.append(("Runs with terminal estate-tax estimate", str(outcomes["terminal_estate_estimate_runs"])))
    denominators = outcomes["denominators"]
    rows.append(("Assessed runs: spending / access / legacy",
                 f"{denominators['spending']} / {denominators['account_access']} / {denominators['legacy']}"))
    years = outcomes["first_funding_shortfall_year_counts"]
    rows.append(("Earliest funding gap (any run)", min(years) if years else "None"))
    for cause, count in outcomes["first_funding_shortfall_cause_counts"].items():
        rows.append((f"First gap: {CAUSE_LABELS.get(cause, cause)} (runs)", str(count)))
    return rows


OUTCOME_EXPLANATION = (
    "Adjusted budgets include modeled expenses, taxes and required housing funding. "
    "Planned spending requires that funding without cuts above one base-year dollar; "
    "it does not test whether a reduced budget could instead have stayed higher. Legacy attainment is "
    "independent and requires after-estate final wealth to meet or exceed the target. "
    "Single-household and stochastic legacy goals use a terminal estate-tax estimate; "
    "this does not change historical cash-flow or combined-success fields. "
    "Rates use all runs except access, which excludes unassessed runs. First-gap "
    "causes can overlap. Combined success preserves the historical joint metric."
)
