"""Mantissa CLI — command-line interface for the retirement planner."""
import click
from tabulate import tabulate

from .engine import RetirementPlanner
from .simulators import MonteCarloEngine
from .reports import (
    generate_summary_report,
    generate_cash_flow_report,
    generate_mc_report,
    export_json,
    export_csv,
    export_markdown,
)
from .pdf_report import generate_pdf_report
from .sensitivity import SensitivityAnalyzer


def _fmt_money(value: float) -> str:
    """Format a float as $X,XXX,XXX."""
    return f"${value:,.0f}"


def _print_mc_results(mc_results: dict, label: str = "MONTE CARLO RESULTS"):
    """Print a formatted summary table of MC results."""
    click.echo()
    click.echo("=" * 52)
    click.echo(f"  {label}")
    click.echo("=" * 52)
    click.echo(f"  Success Rate:        {mc_results['success_rate'] * 100:.1f}%")
    click.echo(f"  Median Final NW:     {_fmt_money(mc_results['median_final_nw'])}")
    click.echo(f"  P10 Final NW:        {_fmt_money(mc_results['p10_final_nw'])}")
    click.echo(f"  P90 Final NW:        {_fmt_money(mc_results['p90_final_nw'])}")
    click.echo(f"  Median Lifetime Tax: {_fmt_money(mc_results['median_taxes'])}")
    click.echo(f"  Out of Savings Rate: {mc_results['out_of_savings_rate'] * 100:.1f}%")
    click.echo(f"  Simulations:         {mc_results['num_simulations']:,}")
    click.echo("=" * 52)
    click.echo()


@click.group()
@click.version_option(version="0.1.0", prog_name="Mantissa")
def main():
    """Mantissa — Open-source retirement planner with Monte Carlo simulation."""
    pass


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--simulations", "-n", default=1000, type=int)
@click.option(
    "--method", "-m", default="gaussian",
    type=click.Choice(["gaussian", "historical"]),
)
@click.option(
    "--scenario", "-s", default="mean",
    type=click.Choice(["mean", "optimistic", "pessimistic"]),
)
@click.option("--output", "-o", default=None, type=click.Path())
def run(config, simulations, method, scenario, output):
    """Run Monte Carlo simulation and display results."""
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    click.echo(f"Running {simulations:,} simulations ({method}, {scenario})...")
    mc_results = mc.run(
        num_simulations=simulations,
        scenario=scenario,
        method=method,
    )

    _print_mc_results(mc_results)

    if output:
        export_json(mc_results, output)
        click.echo(f"Results saved to {output}")


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option(
    "--format", "-f", "fmt", default="markdown",
    type=click.Choice(["json", "csv", "markdown"]),
)
@click.option("--output", "-o", default=None, type=click.Path())
@click.option("--simulations", "-n", default=1000, type=int)
def report(config, fmt, output, simulations):
    """Generate a retirement plan report."""
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    cash_flow = planner.project_cash_flow()
    mc_results = mc.run(num_simulations=simulations)

    summary = generate_summary_report(mc_results, cash_flow)
    cf_report = generate_cash_flow_report(cash_flow)
    mc_report = generate_mc_report(mc_results)

    combined = {
        "summary": summary,
        "monte_carlo": mc_report,
        "cash_flow": cf_report,
    }

    if fmt == "json":
        content = _export_json_str(combined)
    elif fmt == "csv":
        content = _export_csv_str(cash_flow)
    else:
        content = _export_markdown_str(cash_flow)

    if output:
        with open(output, "w") as f:
            f.write(content)
        click.echo(f"Report saved to {output}")
    else:
        click.echo(content)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--output", "-o", default=None, type=click.Path(), help="Output PDF path (default: report.pdf)")
@click.option("--simulations", "-n", default=1000, type=int)
@click.option("--method", "-m", default="gaussian",
              type=click.Choice(["gaussian", "historical"]))
@click.option("--scenario", "-s", default="mean",
              type=click.Choice(["mean", "optimistic", "pessimistic"]))
def pdf(config, output, simulations, method, scenario):
    """Generate a PDF retirement plan report (Boldin-style)."""
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    click.echo(f"Running {simulations:,} simulations ({method}, {scenario})...")
    mc_results = mc.run(
        num_simulations=simulations,
        scenario=scenario,
        method=method,
    )
    cash_flow = planner.project_cash_flow(scenario)

    output = output or "report.pdf"
    click.echo("Generating PDF report...")
    path = generate_pdf_report(planner, mc_results, cash_flow, output)
    click.echo(f"Report saved to {path}")


@main.command()
@click.option("--config1", "-c1", required=True, type=click.Path(exists=True))
@click.option("--config2", "-c2", required=True, type=click.Path(exists=True))
@click.option("--simulations", "-n", default=1000, type=int)
def compare(config1, config2, simulations):
    """Compare two retirement scenarios side by side."""
    planner1 = RetirementPlanner.from_config(config1)
    planner2 = RetirementPlanner.from_config(config2)

    click.echo(f"Running {simulations:,} simulations for each scenario...")

    mc1 = MonteCarloEngine(planner1)
    mc2 = MonteCarloEngine(planner2)

    results1 = mc1.run(num_simulations=simulations)
    results2 = mc2.run(num_simulations=simulations)

    name1 = planner1.scenario.name
    name2 = planner2.scenario.name

    headers = ["Metric", name1, name2]
    rows = [
        ["Success Rate",
         f"{results1['success_rate'] * 100:.1f}%",
         f"{results2['success_rate'] * 100:.1f}%"],
        ["Median Final NW",
         _fmt_money(results1["median_final_nw"]),
         _fmt_money(results2["median_final_nw"])],
        ["P10 Final NW",
         _fmt_money(results1["p10_final_nw"]),
         _fmt_money(results2["p10_final_nw"])],
        ["P90 Final NW",
         _fmt_money(results1["p90_final_nw"]),
         _fmt_money(results2["p90_final_nw"])],
        ["Median Lifetime Tax",
         _fmt_money(results1["median_taxes"]),
         _fmt_money(results2["median_taxes"])],
        ["Out of Savings Rate",
         f"{results1['out_of_savings_rate'] * 100:.1f}%",
         f"{results2['out_of_savings_rate'] * 100:.1f}%"],
    ]

    click.echo()
    click.echo(tabulate(rows, headers=headers, tablefmt="rounded_grid"))
    click.echo()


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option(
    "--variable", "-v", required=True,
    type=click.Choice([
        "inflation", "medical_inflation",
        "housing_appreciation", "investment_return_mean",
    ]),
)
@click.option("--values", "-val", required=True, help="Comma-separated values")
@click.option("--simulations", "-n", default=100, type=int)
@click.option("--output", "-o", default=None, type=click.Path())
def sensitivity(config, variable, values, simulations, output):
    """Run sensitivity analysis on a single variable."""
    try:
        val_list = [float(v.strip()) for v in values.split(",")]
    except ValueError:
        raise click.BadParameter(f"Invalid values: {values}. Must be comma-separated numbers.")

    planner = RetirementPlanner.from_config(config)
    analyzer = SensitivityAnalyzer(planner)

    click.echo(f"Sensitivity analysis: {variable} = {val_list}")
    click.echo(f"Running {simulations} simulations per value...")

    results = analyzer.run(variable, val_list, num_simulations=simulations)

    headers = ["Variable", "Value", "Success Rate", "Avg Final NW"]
    rows = []
    for r in results:
        rows.append([
            r["variable"],
            f"{r['value']}",
            f"{r['success_rate'] * 100:.1f}%",
            _fmt_money(r["avg_final_nw"]),
        ])

    click.echo()
    click.echo(tabulate(rows, headers=headers, tablefmt="rounded_grid"))
    click.echo()

    if output:
        export_json(results, output)
        click.echo(f"Results saved to {output}")


# ---------------------------------------------------------------------------
# Internal helpers for report export
# ---------------------------------------------------------------------------

def _export_json_str(data) -> str:
    import json
    return json.dumps(data, indent=2, default=str)


def _export_csv_str(rows: list) -> str:
    import csv
    import io
    if not rows:
        return ""
    buf = io.StringIO()
    fieldnames = list(rows[0].keys())
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _export_markdown_str(rows: list, title: str = "Retirement Plan Report") -> str:
    if not rows:
        return f"# {title}\n\nNo data.\n"
    headers = list(rows[0].keys())
    lines = [
        f"# {title}\n",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[h]) for h in headers) + " |")
    return "\n".join(lines) + "\n"
