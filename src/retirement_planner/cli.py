"""Mantissa CLI — command-line interface for the retirement planner."""
import click
import json
import csv
import io
from pathlib import Path
from tabulate import tabulate

from . import __version__
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

from .sensitivity import SensitivityAnalyzer
from .formatting import fmt_money as _fmt_money
from .config.validation import validate_config, schema_dict


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
    dist = mc_results.get("mortality_distribution")
    if dist:
        click.echo()
        click.echo("  Stochastic mortality (by age):")
        click.echo(f"  {'Age':>4} {'%Dead':>8} {'%OOM':>8} {'%3x':>8} {'Median NW':>16}")
        for row in dist:
            click.echo(
                f"  {row['age']:>4} {row['pct_dead']*100:>7.1f}%"
                f" {row['pct_out_of_money']*100:>7.1f}%"
                f" {row['pct_3x_target']*100:>7.1f}%"
                f" {_fmt_money(row['median_net_worth']):>16}")
    click.echo()


@click.group()
@click.version_option(version=__version__, prog_name="Mantissa")
def main():
    """Mantissa — Open-source retirement planner with Monte Carlo simulation."""
    pass


def _write_output(content: str, output=None):
    if output:
        path = Path(output)
        if path.exists():
            raise click.ClickException(f"Refusing to overwrite existing file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        click.echo(f"Saved to {path}")
    else:
        click.echo(content, nl=not content.endswith("\n"))


def _load_raw_config(path: str, strict: bool = False):
    try:
        with open(path) as handle:
            raw = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise click.ClickException(f"Unable to read config: {exc}") from exc
    result = validate_config(raw, strict=strict)
    if result.errors:
        detail = "\n".join(f"  {i.path}: {i.message}" for i in result.errors)
        raise click.ClickException("Invalid configuration:\n" + detail)
    return raw, result


def _starter_config() -> dict:
    return {
        "name": "My Retirement Plan",
        "description": "Starter Mantissa scenario",
        "primary": {
            "name": "Primary Person", "birth_date": "1970-01-01",
            "retirement_date": "2035-01-01", "longevity_age": 95,
        },
        "spouse": {
            "name": "Spouse", "birth_date": "1970-01-01",
            "retirement_date": "2035-01-01", "longevity_age": 95,
        },
        "economic": {"inflation": 0.025, "medical_inflation": 0.04,
                      "housing_appreciation": 0.035},
        "accounts": [], "income_streams": [], "expenses": [], "mortgages": [],
        "monetary_convention": "real",
    }


@main.command()
@click.option("--output", "-o", default="my-plan.json", type=click.Path())
def init(output):
    """Create a starter scenario configuration."""
    _write_output(json.dumps(_starter_config(), indent=2) + "\n", output)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--strict", is_flag=True, default=False)
def validate(config, strict):
    """Validate a scenario configuration before simulation."""
    _, result = _load_raw_config(config, strict=strict)
    if result.warnings:
        for issue in result.warnings:
            click.echo(f"Warning: {issue.path}: {issue.message}")
    if not result.valid:
        raise click.ClickException("Configuration is invalid")
    if not json.load(open(config)).get("accounts", []):
        click.echo("Warning: configuration has no accounts")
    click.echo("Configuration is valid")


@main.command(name="schema")
@click.option("--output", "-o", default=None, type=click.Path())
def schema(output):
    """Print or export the supported configuration schema."""
    _write_output(json.dumps(schema_dict(), indent=2) + "\n", output)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["json", "markdown", "table"]))
def inspect(config, fmt):
    """Inspect parsed assumptions and account ownership."""
    planner = RetirementPlanner.from_config(config)
    s = planner.scenario
    data = {
        "name": s.name,
        "primary": s.primary.name,
        "spouse": s.spouse.name,
        "monetary_convention": s.monetary_convention.value,
        "accounts": [{"id": a.id, "type": a.account_type,
                      "tax_treatment": a.tax_treatment, "owner": a.owner,
                      "balance": a.balance} for a in s.accounts],
        "income_streams": len(s.income_streams),
        "expenses": len(s.expenses),
    }
    if fmt == "json":
        click.echo(json.dumps(data, indent=2, default=str))
    elif fmt == "markdown":
        click.echo("# Scenario Inspect\n\n" + "\n".join(
            f"- **{key}:** {value}" for key, value in data.items()))
    else:
        click.echo(tabulate([[k, v] for k, v in data.items()],
                            headers=["Field", "Value"], tablefmt="rounded_grid"))


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["json", "csv", "markdown", "table"]))
@click.option("--output", "-o", default=None, type=click.Path())
def project(config, fmt, output):
    """Run a deterministic annual projection without Monte Carlo noise."""
    rows = RetirementPlanner.from_config(config).project_cash_flow()
    if fmt == "json":
        content = json.dumps(rows, indent=2, default=str)
    elif fmt == "csv":
        if rows:
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
            content = buf.getvalue()
        else:
            content = ""
    elif fmt == "markdown":
        content = _export_markdown_str(rows, "Deterministic Projection")
    else:
        fields = ["year", "income", "expenses", "taxes", "net_worth"]
        content = tabulate([[r.get(f, "") for f in fields] for r in rows],
                           headers=fields, tablefmt="rounded_grid")
    _write_output(content, output)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--year", type=int, required=True)
def explain(config, year):
    """Explain the deterministic projection for one year."""
    rows = RetirementPlanner.from_config(config).project_cash_flow()
    row = next((r for r in rows if r["year"] == year), None)
    if row is None:
        raise click.ClickException(f"Year {year} is outside the projection")
    click.echo(f"Year {year}: ages {row['primary_age']}/{row['spouse_age']}")
    click.echo(f"Income: ${row['income']:,.0f}")
    click.echo(f"Expenses: ${row['expenses']:,.0f}")
    click.echo(f"Taxes: ${row['taxes']:,.0f}")
    click.echo(f"Net worth: ${row['net_worth']:,.0f}")


def _format_equity_breakdown(planner) -> str:
    """Format equity vesting breakdown for CLI output."""
    from tabulate import tabulate

    lines = []
    for stream in planner.scenario.income_streams:
        if not stream.equity or not stream.equity.ticker:
            continue

        eq = stream.equity
        lines.append(f"\n{'='*60}")
        lines.append(f"Equity: {stream.name} ({eq.ticker} @ ${eq.current_price:.2f})")
        lines.append(f"{'='*60}")

        # Build year-by-year vesting table
        start_year = stream.start_date.year
        end_year = stream.end_date.year
        table = []

        for year in range(start_year, min(end_year + 1, start_year + 15)):
            rsu_income = planner.calculate_annual_rsu_income(year, eq)
            shares = rsu_income / eq.current_price if eq.current_price > 0 else 0
            if shares > 0:
                table.append([year, f"{shares:,.1f}", f"${rsu_income:,.0f}"])

        if table:
            headers = ["Year", "Shares Vesting", "RSU Income"]
            lines.append(tabulate(table, headers=headers, tablefmt="simple"))
        else:
            lines.append("  No vesting in projection window.")

        # Active grants summary
        if eq.grants:
            lines.append(f"\n  Active Grants: {len(eq.grants)}")
            for g in eq.grants:
                lines.append(f"    {g.id}: {g.total_shares:,.0f} shares ({g.vesting_pattern})")

        # Refresher summary
        if eq.refreshers:
            rp = eq.refreshers
            lines.append(f"\n  Refresher Policy:")
            lines.append(f"    {rp.annual_shares:,.0f} shares/year, {rp.vesting_pattern}, "
                         f"grant month {rp.grant_month}")
            lines.append(f"    Years {rp.start_year}–{rp.end_year}, "
                         f"growth {rp.growth_rate*100:.1f}%")

    return "\n".join(lines) if lines else ""


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
@click.option("--stress", default=None, type=float,
              help="Stress level 0-1: cut discretionary expenses by "
                   "min_reduction x stress (0 = normal, 1 = max).")
@click.option("--output", "-o", default=None, type=click.Path())
@click.option("--stochastic", is_flag=True, default=False,
              help="Sample a random household death year per run from SSA "
                   "2023 mortality tables (stochastic mortality mode).")
@click.option("--seed", default=None, type=int, help="Seed for reproducible simulations.")
def run(config, simulations, method, scenario, output, seed, stress, stochastic):
    """Run Monte Carlo simulation and display results."""
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    stress_level = stress if stress is not None else planner.stress_level
    click.echo(f"Running {simulations:,} simulations ({method}, {scenario})"
               f"{' @ stress ' + str(stress_level) if stress_level else ''}"
               f"{' [stochastic mortality]' if stochastic else ''}...")
    mc_results = mc.run(
        num_simulations=simulations,
        scenario=scenario,
        method=method,
        seed=seed,
        stress_level=stress_level,
        stochastic=stochastic,
    )

    _print_mc_results(mc_results)

    if output:
        export_json(mc_results, output)
        click.echo(f"Results saved to {output}")


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--simulations", "-n", default=500, type=int)
@click.option("--levels", "-l", default="0,0.25,0.5,0.75,1",
              help="Comma-separated stress levels to test.")
@click.option("--method", "-m", default="gaussian",
              type=click.Choice(["gaussian", "historical"]))
@click.option("--scenario", "-s", default="mean",
              type=click.Choice(["mean", "optimistic", "pessimistic"]))
@click.option("--seed", default=None, type=int)
def stress(config, simulations, levels, method, scenario, seed):
    """Stress-test the plan: MC success across discretionary-cut levels.

    At each level, non-essential expenses (is_must_spend=false) are cut
    by their min_reduction x level.  Shows how much the plan cushions
    a spending pullback — and which expenses get cut.
    """
    try:
        level_list = [float(v.strip()) for v in levels.split(",")]
    except ValueError:
        raise click.BadParameter(
            f"Invalid levels: {levels}. Must be comma-separated numbers.")
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    discretionary = [
        e for e in planner.scenario.expenses
        if not e.is_must_spend and not e.is_one_time
        and e.min_reduction > 0
    ]
    if discretionary:
        click.echo("Discretionary expenses (cut under stress):")
        for e in sorted(discretionary, key=lambda x: -x.min_reduction):
            click.echo(f"  {e.name}: -{e.min_reduction*100:.0f}% max cut")
        click.echo()
    else:
        click.echo("No discretionary expenses with min_reduction set — "
                   "stress levels will have no effect.\n")

    click.echo(f"Running {simulations:,} simulations per level...")
    headers = ["Stress", "Success", "Median NW", "P10 NW", "OOS Rate"]
    rows = []
    for level in level_list:
        r = mc.run(num_simulations=simulations, scenario=scenario,
                   method=method, seed=seed, stress_level=level)
        rows.append([
            f"{level:.0%}",
            f"{r['success_rate']*100:.1f}%",
            _fmt_money(r["median_final_nw"]),
            _fmt_money(r["p10_final_nw"]),
            f"{r['out_of_savings_rate']*100:.1f}%",
        ])
    click.echo(tabulate(rows, headers=headers, tablefmt="rounded_grid"))


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option(
    "--format", "-f", "fmt", default="markdown",
    type=click.Choice(["json", "csv", "markdown"]),
)
@click.option("--output", "-o", default=None, type=click.Path())
@click.option("--simulations", "-n", default=1000, type=int)
@click.option("--stress", default=None, type=float,
              help="Stress level 0-1: cut discretionary expenses.")
@click.option("--show-equity", is_flag=True, default=False,
              help="Include equity vesting breakdown in report.")
def report(config, fmt, output, simulations, stress, show_equity):
    """Generate a retirement plan report."""
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    stress_level = stress if stress is not None else planner.stress_level
    cash_flow = planner.project_cash_flow(stress_level=stress_level)
    mc_results = mc.run(num_simulations=simulations, stress_level=stress_level)

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

    # Equity breakdown (optional)
    if show_equity:
        equity_lines = _format_equity_breakdown(planner)
        if equity_lines:
            click.echo("\n" + equity_lines)


@main.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True))
@click.option("--output", "-o", default=None, type=click.Path(), help="Output PDF path (default: report.pdf)")
@click.option("--simulations", "-n", default=1000, type=int)
@click.option("--method", "-m", default="gaussian",
              type=click.Choice(["gaussian", "historical"]))
@click.option("--scenario", "-s", default="mean",
              type=click.Choice(["mean", "optimistic", "pessimistic"]))
@click.option("--stress", default=None, type=float,
              help="Stress level 0-1: cut discretionary expenses.")
def pdf(config, output, simulations, method, scenario, stress):
    """Generate a PDF retirement plan report (Boldin-style)."""
    try:
        from .pdf_report import generate_pdf_report
    except ImportError as exc:
        raise click.ClickException("PDF support requires the optional 'reportlab' dependency") from exc
    planner = RetirementPlanner.from_config(config)
    mc = MonteCarloEngine(planner)

    stress_level = stress if stress is not None else planner.stress_level
    click.echo(f"Running {simulations:,} simulations ({method}, {scenario})...")
    mc_results = mc.run(
        num_simulations=simulations,
        scenario=scenario,
        method=method,
        stress_level=stress_level,
    )
    cash_flow = planner.project_cash_flow(scenario, stress_level=stress_level)

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


# ---------------------------------------------------------------------------
# doctor — dependency and environment checks
# ---------------------------------------------------------------------------
OPTIONAL_DEPS = {
    "matplotlib": {
        "package": "matplotlib",
        "feature": "charts",
        "install": "pip install mantissa[charts]",
    },
    "reportlab": {
        "package": "reportlab",
        "feature": "pdf",
        "install": "pip install mantissa[pdf]",
    },
}


@main.command()
def doctor():
    """Check environment and optional dependency availability."""
    import importlib
    import importlib.metadata
    import sys

    click.echo("Mantissa Doctor")
    click.echo(f"  Python: {sys.version.split()[0]}")
    click.echo()

    # Core dependencies
    click.echo("Core dependencies:")
    for pkg in ["click", "numpy", "tabulate"]:
        try:
            mod = importlib.import_module(pkg)
            version = importlib.metadata.version(pkg)
            click.echo(f"  ✓ {pkg} ({version})")
        except (ImportError, importlib.metadata.PackageNotFoundError):
            click.echo(f"  ✗ {pkg} — MISSING (required)")
    click.echo()

    # Optional dependencies
    click.echo("Optional dependencies:")
    all_ok = True
    for name, info in OPTIONAL_DEPS.items():
        try:
            mod = importlib.import_module(name)
            version = importlib.metadata.version(info["package"])
            click.echo(f"  ✓ {name} ({version}) — {info['feature']}")
        except (ImportError, importlib.metadata.PackageNotFoundError):
            click.echo(f"  ✗ {name} — not installed")
            click.echo(f"    Install: {info['install']}")
            all_ok = False
    click.echo()

    if all_ok:
        click.echo("All optional dependencies are installed.")
    else:
        click.echo("Some optional features are unavailable.")
        click.echo("Install all: pip install mantissa[all]")


if __name__ == "__main__":
    main()
