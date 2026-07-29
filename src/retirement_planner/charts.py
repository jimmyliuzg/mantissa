"""
Matplotlib-based chart generation for the retirement planner.

All functions use the non-interactive Agg backend and save figures to disk.
"""
from typing import Any, Dict, List, Optional
from .formatting import fmt_money as _fmt_dollar


def _require_matplotlib():
    """Lazy-import matplotlib; raise helpful error if missing."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        return matplotlib, plt
    except ImportError:
        raise ImportError(
            "matplotlib is required for chart generation. "
            "Install it with: pip install matplotlib"
        )


def plot_net_worth_trajectory(
    cash_flow: List[Dict[str, Any]],
    output_path: str,
    title: str = "Net Worth Trajectory",
) -> str:
    """Line chart of net worth over years with fill.

    Parameters
    ----------
    cash_flow : list of dict
        Each dict must have 'year' and 'net_worth' keys.
    output_path : str
        File path to save the chart (e.g. 'chart.png').
    title : str
        Chart title.

    Returns
    -------
    str
        The output_path that was saved to.
    """
    _, plt = _require_matplotlib()

    years = [row["year"] for row in cash_flow]
    net_worths = [row["net_worth"] for row in cash_flow]

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(years, net_worths, color="#2563eb", linewidth=2)
    ax.fill_between(years, net_worths, alpha=0.15, color="#2563eb")
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_xlabel("Year")
    ax.set_ylabel("Net Worth")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: _fmt_dollar(x)))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    try:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)
    return output_path


def plot_mc_fan_chart(
    mc_results: Dict[str, Any],
    output_path: str,
    title: str = "Monte Carlo Projection",
) -> str:
    """Bar chart of percentile values from Monte Carlo results.

    Parameters
    ----------
    mc_results : dict
        Must contain a 'percentiles' list of dicts with 'label' and 'value' keys.
    output_path : str
        File path to save the chart.
    title : str
        Chart title.

    Returns
    -------
    str
        The output_path that was saved to.
    """
    _, plt = _require_matplotlib()

    percentiles = mc_results["percentiles"]
    labels = [p["label"] for p in percentiles]
    values = [p["value"] for p in percentiles]

    colors = ["#3b82f6", "#60a5fa", "#2563eb", "#60a5fa", "#3b82f6"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors[: len(labels)], edgecolor="white")
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.01,
            _fmt_dollar(val),
            ha="center",
            va="bottom",
            fontsize=10,
        )
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("Portfolio Value")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: _fmt_dollar(x)))
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    try:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)
    return output_path


def plot_income_vs_expenses(
    cash_flow: List[Dict[str, Any]],
    output_path: str,
    title: str = "Income vs Expenses",
) -> str:
    """Grouped bar chart of income and expenses by year.

    Parameters
    ----------
    cash_flow : list of dict
        Each dict must have 'year', 'income', and 'expenses' keys.
    output_path : str
        File path to save the chart.
    title : str
        Chart title.

    Returns
    -------
    str
        The output_path that was saved to.
    """
    _, plt = _require_matplotlib()

    years = [str(row["year"]) for row in cash_flow]
    incomes = [row["income"] for row in cash_flow]
    expenses = [row["expenses"] for row in cash_flow]

    x = range(len(years))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar([i - width / 2 for i in x], incomes, width, label="Income", color="#22c55e")
    ax.bar([i + width / 2 for i in x], expenses, width, label="Expenses", color="#ef4444")
    ax.set_xticks(list(x))
    ax.set_xticklabels(years)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("Amount")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: _fmt_dollar(x)))
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    try:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)
    return output_path


def plot_tax_breakdown(
    cash_flow: List[Dict[str, Any]],
    output_path: str,
    title: str = "Lifetime Tax Burden",
) -> str:
    """Bar chart of annual taxes with cumulative line overlay.

    Parameters
    ----------
    cash_flow : list of dict
        Each dict must have 'year' and 'taxes' keys.
    output_path : str
        File path to save the chart.
    title : str
        Chart title.

    Returns
    -------
    str
        The output_path that was saved to.
    """
    _, plt = _require_matplotlib()

    years = [str(row["year"]) for row in cash_flow]
    taxes = [row["taxes"] for row in cash_flow]
    cumulative = []
    running = 0
    for t in taxes:
        running += t
        cumulative.append(running)

    fig, ax1 = plt.subplots(figsize=(10, 5))
    ax1.bar(years, taxes, color="#f59e0b", alpha=0.8, label="Annual Taxes")
    ax1.set_title(title, fontsize=14, fontweight="bold")
    ax1.set_ylabel("Annual Taxes")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: _fmt_dollar(x)))

    ax2 = ax1.twinx()
    ax2.plot(years, cumulative, color="#dc2626", linewidth=2, marker="o", label="Cumulative")
    ax2.set_ylabel("Cumulative Taxes")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: _fmt_dollar(x)))

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
    ax1.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    try:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
    finally:
        plt.close(fig)
    return output_path
