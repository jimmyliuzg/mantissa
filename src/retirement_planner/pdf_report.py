"""
PDF report generation for the retirement planner.

Produces a multi-section PDF report modeled after Boldin's printable report.
Sections:
  1. Cover Page
  2. Plan Summary (key metrics dashboard)
  3. Current Net Worth (account breakdown + pie chart)
  4. Income & Expenses (year-by-year chart + summary)
  5. Cash Flow Projection (annual table)
  6. Tax Summary (annual + cumulative chart)
  7. Monte Carlo Results (success rate, percentiles, fan chart)
  8. Net Worth Trajectory (projected growth chart)
  9. Plan Assumptions (rates, SS, withdrawal strategy)
  10. Appendix (detailed cash flow table)

Usage:
    from retirement_planner.pdf_report import generate_pdf_report
    generate_pdf_report(planner, mc_results, cash_flow, "report.pdf")
"""
from __future__ import annotations

import tempfile
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image, KeepTogether, HRFlowable,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Wedge
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF


# ---------------------------------------------------------------------------
# Color palette (Boldin-inspired: blues + grays)
# ---------------------------------------------------------------------------
PRIMARY_BLUE = colors.HexColor("#1a56db")
LIGHT_BLUE = colors.HexColor("#dbeafe")
DARK_GRAY = colors.HexColor("#374151")
MEDIUM_GRAY = colors.HexColor("#6b7280")
LIGHT_GRAY = colors.HexColor("#f3f4f6")
GREEN = colors.HexColor("#059669")
RED = colors.HexColor("#dc2626")
AMBER = colors.HexColor("#d97706")
PIE_COLORS = [
    colors.HexColor("#1a56db"), colors.HexColor("#059669"),
    colors.HexColor("#d97706"), colors.HexColor("#dc2626"),
    colors.HexColor("#7c3aed"), colors.HexColor("#0891b2"),
    colors.HexColor("#be185d"), colors.HexColor("#65a30d"),
]


# ---------------------------------------------------------------------------
# Helpers — use shared formatting
# ---------------------------------------------------------------------------
from .formatting import fmt_money_millions as _fmt_money
from .formatting import fmt_pct as _fmt_pct


def _styles():
    """Return custom paragraph styles."""
    ss = getSampleStyleSheet()
    styles = {
        "Title": ParagraphStyle(
            "ReportTitle", parent=ss["Title"],
            fontSize=28, leading=34, textColor=PRIMARY_BLUE,
            spaceAfter=6,
        ),
        "Subtitle": ParagraphStyle(
            "ReportSubtitle", parent=ss["Normal"],
            fontSize=14, leading=18, textColor=MEDIUM_GRAY,
            alignment=TA_CENTER, spaceAfter=20,
        ),
        "SectionHead": ParagraphStyle(
            "SectionHead", parent=ss["Heading1"],
            fontSize=18, leading=22, textColor=PRIMARY_BLUE,
            spaceBefore=24, spaceAfter=10,
            borderWidth=0, borderPadding=0,
        ),
        "SubHead": ParagraphStyle(
            "SubHead", parent=ss["Heading2"],
            fontSize=13, leading=16, textColor=DARK_GRAY,
            spaceBefore=12, spaceAfter=6,
        ),
        "Body": ParagraphStyle(
            "Body", parent=ss["Normal"],
            fontSize=10, leading=14, textColor=DARK_GRAY,
        ),
        "BodySmall": ParagraphStyle(
            "BodySmall", parent=ss["Normal"],
            fontSize=8, leading=10, textColor=MEDIUM_GRAY,
        ),
        "Metric": ParagraphStyle(
            "Metric", parent=ss["Normal"],
            fontSize=22, leading=26, textColor=PRIMARY_BLUE,
            alignment=TA_CENTER, fontName="Helvetica-Bold",
        ),
        "MetricLabel": ParagraphStyle(
            "MetricLabel", parent=ss["Normal"],
            fontSize=9, leading=12, textColor=MEDIUM_GRAY,
            alignment=TA_CENTER,
        ),
        "Right": ParagraphStyle(
            "Right", parent=ss["Normal"],
            fontSize=10, leading=14, textColor=DARK_GRAY,
            alignment=TA_RIGHT,
        ),
        "Footer": ParagraphStyle(
            "Footer", parent=ss["Normal"],
            fontSize=8, leading=10, textColor=MEDIUM_GRAY,
            alignment=TA_CENTER,
        ),
    }
    return styles


def _hr() -> HRFlowable:
    """Thin horizontal rule."""
    return HRFlowable(width="100%", thickness=1, color=LIGHT_GRAY, spaceAfter=8, spaceBefore=8)


def _make_table(data: List[List], col_widths: Optional[List[float]] = None,
                header: bool = True) -> Table:
    """Create a styled table."""
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    # Alternate row shading
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), LIGHT_GRAY))
    t.setStyle(TableStyle(style_cmds))
    return t


def _metric_cell(value: str, label: str, styles: dict) -> List:
    """Return a [value, label] paragraph pair for metric cards."""
    return [
        Paragraph(value, styles["Metric"]),
        Paragraph(label, styles["MetricLabel"]),
    ]


def _pie_chart(labels: List[str], values: List[float], title: str = "",
               width: int = 300, height: int = 200) -> Drawing:
    """Create a pie chart drawing."""
    d = Drawing(width, height)
    pie = Pie()
    pie.x = 60
    pie.y = 20
    pie.width = 140
    pie.height = 140
    pie.data = values
    pie.labels = [f"{l}: {_fmt_money(v)}" for l, v in zip(labels, values)]
    pie.slices.fontName = "Helvetica"
    pie.slices.fontSize = 7
    pie.slices.strokeWidth = 0.5
    pie.slices.strokeColor = colors.white
    for i, c in enumerate(PIE_COLORS[:len(values)]):
        pie.slices[i].fillColor = c
    d.add(pie)
    if title:
        d.add(String(width / 2, height - 10, title,
                      fontSize=10, fontName="Helvetica-Bold",
                      fillColor=DARK_GRAY, textAnchor="middle"))
    return d


def _bar_chart(categories: List[str], series: Dict[str, List[float]],
               title: str = "", width: int = 480, height: int = 200) -> Drawing:
    """Create a grouped bar chart drawing."""
    d = Drawing(width, height)
    bc = VerticalBarChart()
    bc.x = 60
    bc.y = 30
    bc.width = width - 100
    bc.height = height - 60
    bc.data = list(series.values())
    bc.categoryAxis.categoryNames = categories
    bc.categoryAxis.labels.fontName = "Helvetica"
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.angle = 0
    bc.valueAxis.labels.fontName = "Helvetica"
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labelTextFormat = "$%s"
    bc.bars.strokeWidth = 0
    bc.barSpacing = 1
    bc.groupSpacing = 8
    bar_colors = [PRIMARY_BLUE, GREEN, RED, AMBER]
    for i, name in enumerate(series.keys()):
        bc.bars[i].fillColor = bar_colors[i % len(bar_colors)]
    d.add(bc)
    # Legend
    legend_y = height - 18
    legend_x = 70
    for i, name in enumerate(series.keys()):
        c = bar_colors[i % len(bar_colors)]
        d.add(Rect(legend_x, legend_y - 4, 10, 10, fillColor=c, strokeColor=None))
        d.add(String(legend_x + 14, legend_y - 2, name, fontSize=8, fontName="Helvetica", fillColor=DARK_GRAY))
        legend_x += len(name) * 5 + 30
    if title:
        d.add(String(width / 2, height - 5, title,
                      fontSize=10, fontName="Helvetica-Bold",
                      fillColor=DARK_GRAY, textAnchor="middle"))
    return d


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _section_cover(styles: dict, scenario, generated_at: str) -> list:
    """Cover page elements."""
    elements = []
    elements.append(Spacer(1, 1.5 * inch))
    elements.append(Paragraph("Mantissa", styles["Title"]))
    elements.append(Paragraph("Retirement Plan Report", styles["Subtitle"]))
    elements.append(Spacer(1, 0.3 * inch))

    # Plan info card
    info_data = [
        ["Plan Name", scenario.name],
        ["Primary", f"{scenario.primary.name} (b. {scenario.primary.birth_date})"],
        ["Spouse", f"{scenario.spouse.name} (b. {scenario.spouse.birth_date})"],
        ["Primary Retirement", str(scenario.primary.retirement_date)],
        ["Spouse Retirement", str(scenario.spouse.retirement_date)],
        ["State", scenario.state],
        ["Legacy Goal", _fmt_money(scenario.legacy_goal)],
        ["Generated", generated_at],
    ]
    t = Table(info_data, colWidths=[2 * inch, 4 * inch])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), MEDIUM_GRAY),
        ("TEXTCOLOR", (1, 0), (1, -1), DARK_GRAY),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.5, LIGHT_GRAY),
    ]))
    elements.append(t)
    elements.append(PageBreak())
    return elements


def _section_summary(styles: dict, mc_results: dict, cash_flow: list) -> list:
    """Plan Summary — key metrics dashboard."""
    elements = []
    elements.append(Paragraph("Plan Summary", styles["SectionHead"]))
    elements.append(_hr())

    success_rate = mc_results.get("success_rate", 0.0)
    median_nw = mc_results.get("median_final_nw", 0.0)
    p10_nw = mc_results.get("p10_final_nw", 0.0)
    p90_nw = mc_results.get("p90_final_nw", 0.0)
    median_taxes = mc_results.get("median_taxes", 0.0)
    out_of_savings = mc_results.get("out_of_savings_rate", 0.0)

    # Color-code success rate
    sr_color = GREEN if success_rate >= 0.80 else (AMBER if success_rate >= 0.60 else RED)
    sr_style = ParagraphStyle("SR", parent=styles["Metric"], textColor=sr_color)

    # Metric cards — 3 columns
    metrics = [
        [Paragraph(_fmt_pct(success_rate), sr_style), Paragraph("Success Rate", styles["MetricLabel"])],
        [Paragraph(_fmt_money(median_nw), styles["Metric"]), Paragraph("Median Final Net Worth", styles["MetricLabel"])],
        [Paragraph(str(mc_results.get("num_simulations", 0)), styles["Metric"]), Paragraph("Simulations Run", styles["MetricLabel"])],
    ]
    mt = Table(metrics, colWidths=[2.2 * inch] * 3)
    mt.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (0, -1), 1, LIGHT_GRAY),
        ("BOX", (1, 0), (1, -1), 1, LIGHT_GRAY),
        ("BOX", (2, 0), (2, -1), 1, LIGHT_GRAY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    elements.append(mt)
    elements.append(Spacer(1, 0.2 * inch))

    # Secondary metrics
    secondary = [
        ["P10 Final Net Worth", _fmt_money(p10_nw)],
        ["P90 Final Net Worth", _fmt_money(p90_nw)],
        ["Median Lifetime Taxes", _fmt_money(median_taxes)],
        ["Out of Savings Rate", _fmt_pct(out_of_savings)],
        ["Years of Data", str(len(cash_flow))],
    ]
    st = _make_table([["Metric", "Value"]] + secondary, col_widths=[3.5 * inch, 3 * inch])
    elements.append(st)
    elements.append(Spacer(1, 0.15 * inch))
    return elements


def _section_net_worth(styles: dict, accounts: list) -> list:
    """Current Net Worth — account breakdown with pie chart."""
    elements = []
    elements.append(Paragraph("Current Net Worth", styles["SectionHead"]))
    elements.append(_hr())

    # Build account rows
    total = sum(a.balance for a in accounts)
    rows = []
    chart_labels = []
    chart_values = []
    for a in sorted(accounts, key=lambda x: x.balance, reverse=True):
        if a.balance <= 0:
            continue
        rows.append([a.name, a.account_type.title(), _fmt_money(a.balance),
                      _fmt_pct(a.balance / total) if total > 0 else "0%"])
        chart_labels.append(a.name)
        chart_values.append(a.balance)

    rows.insert(0, ["Account", "Type", "Balance", "% of Total"])
    rows.append(["TOTAL", "", _fmt_money(total), "100%"])

    t = _make_table(rows, col_widths=[2.2 * inch, 1.5 * inch, 1.5 * inch, 1.3 * inch])
    elements.append(t)
    elements.append(Spacer(1, 0.15 * inch))

    # Pie chart
    if chart_values:
        pie = _pie_chart(chart_labels, chart_values)
        elements.append(pie)

    elements.append(PageBreak())
    return elements


def _section_income_expenses(styles: dict, cash_flow: list) -> list:
    """Income & Expenses — chart + summary table."""
    elements = []
    elements.append(Paragraph("Income & Expenses", styles["SectionHead"]))
    elements.append(_hr())

    # Sample years (every 5th year + first/last)
    indices = list(range(0, len(cash_flow), 5))
    if len(cash_flow) - 1 not in indices:
        indices.append(len(cash_flow) - 1)
    sample = [cash_flow[i] for i in indices]

    # Chart
    categories = [str(r["year"]) for r in sample]
    series = {
        "Income": [r["income"] for r in sample],
        "Expenses": [r["expenses"] for r in sample],
    }
    chart = _bar_chart(categories, series, "Income vs Expenses (Selected Years)")
    elements.append(chart)
    elements.append(Spacer(1, 0.15 * inch))

    # Summary table (first 5, middle 5, last 5 years)
    table_rows = [["Year", "Income", "Expenses", "Net Cash Flow", "Taxes"]]
    for r in cash_flow:
        table_rows.append([
            str(r["year"]),
            _fmt_money(r["income"]),
            _fmt_money(r["expenses"]),
            _fmt_money(r.get("net_cash_flow", 0)),
            _fmt_money(r.get("taxes", 0)),
        ])
    # Abbreviate: show first 5, "...", last 5
    if len(table_rows) > 12:
        display = [table_rows[0]] + table_rows[1:6] + [["...", "", "", "", ""]] + table_rows[-5:]
    else:
        display = table_rows
    t = _make_table(display, col_widths=[0.8 * inch, 1.3 * inch, 1.3 * inch, 1.3 * inch, 1.3 * inch])
    elements.append(Paragraph("Annual Cash Flow (abbreviated)", styles["SubHead"]))
    elements.append(t)
    elements.append(PageBreak())
    return elements


def _section_equity_vesting(styles: dict, planner) -> list:
    """Equity Vesting Timeline — year-by-year RSU vesting by ticker."""
    elements = []
    elements.append(Paragraph("Equity Vesting Timeline", styles["SectionHead"]))
    elements.append(_hr())

    has_equity = False
    for stream in planner.scenario.income_streams:
        if not stream.equity or not stream.equity.ticker:
            continue
        has_equity = True
        eq = stream.equity

        # Header
        elements.append(Paragraph(
            f"{stream.name} — {eq.ticker} @ ${eq.current_price:,.2f}",
            styles["SubHead"]
        ))
        elements.append(Spacer(1, 0.1 * inch))

        # Year-by-year data
        start_year = planner.start_year
        end_year = min(stream.end_date.year, start_year + 20)
        categories = []
        shares_data = []
        income_data = []

        for year in range(start_year, end_year + 1):
            rsu_income = planner.calculate_annual_rsu_income(year, eq)
            shares = rsu_income / eq.current_price if eq.current_price > 0 else 0
            if shares > 0:
                categories.append(str(year))
                shares_data.append(shares)
                income_data.append(rsu_income)

        if categories:
            # Bar chart: shares vesting by year
            chart = _bar_chart(
                categories,
                {"Shares Vesting": shares_data},
                f"{eq.ticker} Shares Vesting by Year",
                width=480, height=180,
            )
            elements.append(chart)
            elements.append(Spacer(1, 0.1 * inch))

            # Summary table
            table_rows = [["Year", "Shares", "RSU Income"]]
            for i, yr in enumerate(categories):
                table_rows.append([yr, f"{shares_data[i]:,.1f}", f"${income_data[i]:,.0f}"])
            t = _make_table(table_rows, col_widths=[1.0*inch, 1.2*inch, 1.5*inch])
            elements.append(t)
            elements.append(Spacer(1, 0.15 * inch))

        # Active grants + refresher summary
        summary_parts = []
        if eq.grants:
            summary_parts.append(f"Active Grants: {len(eq.grants)}")
            for g in eq.grants:
                summary_parts.append(f"  {g.id}: {g.total_shares:,.0f} shares ({g.vesting_pattern})")
        if eq.refreshers:
            rp = eq.refreshers
            summary_parts.append(
                f"Refresher: {rp.annual_shares:,.0f} shares/yr, {rp.vesting_pattern}, "
                f"grant month {rp.grant_month}, years {rp.start_year}–{rp.end_year}"
            )
        if summary_parts:
            elements.append(Paragraph("<br/>".join(summary_parts), styles["Body"]))
            elements.append(Spacer(1, 0.15 * inch))

    if not has_equity:
        elements.append(Paragraph("No equity compensation configured.", styles["Body"]))

    elements.append(PageBreak())
    return elements


def _section_tax_summary(styles: dict, cash_flow: list) -> list:
    """Tax Summary — chart + cumulative."""
    elements = []
    elements.append(Paragraph("Tax Summary", styles["SectionHead"]))
    elements.append(_hr())

    # Cumulative taxes
    cumulative = []
    running = 0
    for r in cash_flow:
        running += r.get("taxes", 0)
        cumulative.append(running)

    # Chart: every 5th year
    indices = list(range(0, len(cash_flow), 5))
    if len(cash_flow) - 1 not in indices:
        indices.append(len(cash_flow) - 1)
    sample = [(cash_flow[i], cumulative[i]) for i in indices]

    categories = [str(r["year"]) for r, _ in sample]
    series = {
        "Annual Tax": [r.get("taxes", 0) for r, _ in sample],
    }
    chart = _bar_chart(categories, series, "Annual Taxes (Selected Years)")
    elements.append(chart)
    elements.append(Spacer(1, 0.1 * inch))

    # Cumulative summary
    elements.append(Paragraph(f"Lifetime cumulative tax burden: <b>{_fmt_money(cumulative[-1])}</b>",
                              styles["Body"]))
    elements.append(Spacer(1, 0.1 * inch))

    # Tax table (abbreviated)
    table_rows = [["Year", "Annual Tax", "Cumulative Tax"]]
    for r, c in zip(cash_flow, cumulative):
        table_rows.append([str(r["year"]), _fmt_money(r.get("taxes", 0)), _fmt_money(c)])
    # Abbreviate
    display = [table_rows[0]] + table_rows[1:6]
    if len(table_rows) > 11:
        display.append(["...", "", ""])
    display += table_rows[-5:]
    t = _make_table(display, col_widths=[1.5 * inch, 2.2 * inch, 2.2 * inch])
    elements.append(t)
    elements.append(PageBreak())
    return elements


def _section_monte_carlo(styles: dict, mc_results: dict) -> list:
    """Monte Carlo Results — success rate, percentiles, analysis."""
    elements = []
    elements.append(Paragraph("Monte Carlo Analysis", styles["SectionHead"]))
    elements.append(_hr())

    success_rate = mc_results.get("success_rate", 0.0)
    sr_color = GREEN if success_rate >= 0.80 else (AMBER if success_rate >= 0.60 else RED)
    sr_style = ParagraphStyle("SR2", parent=styles["Metric"], textColor=sr_color)

    # Key metric
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(_fmt_pct(success_rate), sr_style))
    elements.append(Spacer(1, 0.05 * inch))
    elements.append(Paragraph("Probability of Success", styles["MetricLabel"]))
    elements.append(Spacer(1, 0.2 * inch))

    # Percentile table
    percentiles = mc_results.get("percentiles", [])
    if percentiles:
        p_rows = [["Percentile", "Final Net Worth", "Interpretation"]]
        interp_map = {
            10: "Worst realistic case",
            25: "Below average",
            50: "Expected outcome",
            75: "Above average",
            90: "Best realistic case",
        }
        for p in percentiles:
            pct = p.get("percentile", p.get("label", ""))
            val = p.get("value", 0)
            p_rows.append([f"P{pct}", _fmt_money(val), interp_map.get(pct, "")])
        t = _make_table(p_rows, col_widths=[1.2 * inch, 2 * inch, 3 * inch])
        elements.append(t)
    elements.append(Spacer(1, 0.15 * inch))

    # Additional details
    details = [
        ["Method", mc_results.get("method", "gaussian")],
        ["Scenario", mc_results.get("scenario", "mean")],
        ["Median Peak Net Worth", _fmt_money(mc_results.get("median_peak_nw", 0))],
        ["Out of Savings Rate", _fmt_pct(mc_results.get("out_of_savings_rate", 0))],
        ["Simulations", str(mc_results.get("num_simulations", 0))],
    ]
    dt = _make_table([["Parameter", "Value"]] + details, col_widths=[2.5 * inch, 3.5 * inch])
    elements.append(dt)
    elements.append(PageBreak())
    return elements


def _section_net_worth_trajectory(styles: dict, cash_flow: list) -> list:
    """Net Worth Trajectory — projected growth over time."""
    elements = []
    elements.append(Paragraph("Net Worth Trajectory", styles["SectionHead"]))
    elements.append(_hr())

    # Chart
    indices = list(range(0, len(cash_flow), 5))
    if len(cash_flow) - 1 not in indices:
        indices.append(len(cash_flow) - 1)
    sample = [cash_flow[i] for i in indices]

    categories = [str(r["year"]) for r in sample]
    series = {"Net Worth": [r.get("net_worth", 0) for r in sample]}
    chart = _bar_chart(categories, series, "Projected Net Worth")
    elements.append(chart)
    elements.append(Spacer(1, 0.15 * inch))

    # Key milestones
    first = cash_flow[0] if cash_flow else {}
    last = cash_flow[-1] if cash_flow else {}
    elements.append(Paragraph(
        f"Starting net worth ({first.get('year', '?')}): <b>{_fmt_money(first.get('net_worth', 0))}</b>",
        styles["Body"]))
    elements.append(Paragraph(
        f"Ending net worth ({last.get('year', '?')}): <b>{_fmt_money(last.get('net_worth', 0))}</b>",
        styles["Body"]))
    if first.get("net_worth", 0) > 0:
        growth = (last.get("net_worth", 0) / first.get("net_worth", 1)) - 1
        elements.append(Paragraph(f"Total growth: <b>{_fmt_pct(growth)}</b>", styles["Body"]))

    elements.append(PageBreak())
    return elements


def _section_assumptions(styles: dict, scenario) -> list:
    """Plan Assumptions — all inputs."""
    elements = []
    elements.append(Paragraph("Plan Assumptions", styles["SectionHead"]))
    elements.append(_hr())

    # Economic assumptions
    elements.append(Paragraph("Economic Rates", styles["SubHead"]))
    econ = scenario.economic
    rate_rows = [
        ["Rate", "Base", "Optimistic", "Pessimistic"],
        ["General Inflation", _fmt_pct(econ.general_inflation), _fmt_pct(econ.general_inflation_optimistic), _fmt_pct(econ.general_inflation_pessimistic)],
        ["Medical Inflation", _fmt_pct(econ.medical_inflation), _fmt_pct(econ.medical_inflation_optimistic), _fmt_pct(econ.medical_inflation_pessimistic)],
        ["Housing Appreciation", _fmt_pct(econ.housing_appreciation), _fmt_pct(econ.housing_appreciation_optimistic), _fmt_pct(econ.housing_appreciation_pessimistic)],
        ["SS COLA", _fmt_pct(econ.ss_cola), _fmt_pct(econ.ss_cola_optimistic), _fmt_pct(econ.ss_cola_pessimistic)],
    ]
    t = _make_table(rate_rows, col_widths=[1.8 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    elements.append(t)
    elements.append(Spacer(1, 0.15 * inch))

    # Social Security
    elements.append(Paragraph("Social Security", styles["SubHead"]))
    ss = scenario.social_security
    ss_rows = [
        ["", "Primary", "Spouse"],
        ["Benefit at 67", _fmt_money(ss.primary_benefit_at_67 * 12) + "/yr", _fmt_money(ss.spouse_benefit_at_67 * 12) + "/yr"],
        ["Claiming Age", str(ss.primary_claiming_age), str(ss.spouse_claiming_age)],
        ["COLA Rate", _fmt_pct(ss.cola_rate), _fmt_pct(ss.cola_rate)],
    ]
    t = _make_table(ss_rows, col_widths=[2 * inch, 2.2 * inch, 2.2 * inch])
    elements.append(t)
    elements.append(Spacer(1, 0.15 * inch))

    # Withdrawal strategy
    elements.append(Paragraph("Withdrawal Strategy", styles["SubHead"]))
    ws_rows = [
        ["Strategy", scenario.withdrawal_strategy],
        ["Withdrawal Rate", _fmt_pct(scenario.withdrawal_rate)],
        ["Guardrail Floor", _fmt_pct(scenario.guardrail_floor_pct)],
        ["Guardrail Ceiling", _fmt_pct(scenario.guardrail_ceiling_pct)],
    ]
    t = _make_table(ws_rows, col_widths=[2.5 * inch, 3.5 * inch])
    elements.append(t)
    elements.append(Spacer(1, 0.15 * inch))

    # Account summary
    elements.append(Paragraph("Accounts", styles["SubHead"]))
    acct_rows = [["Account", "Type", "Tax Treatment", "Balance", "Growth Rate"]]
    for a in scenario.accounts:
        growth = (f"{a.growth_rate:.1%}" if a.growth_rate is not None
                  else "CMA")  # None = capital-market assumptions
        acct_rows.append([
            a.name, a.account_type.title(), a.tax_treatment,
            _fmt_money(a.balance), growth,
        ])
    t = _make_table(acct_rows, col_widths=[1.5 * inch, 1.2 * inch, 1.2 * inch, 1.3 * inch, 1.2 * inch])
    elements.append(t)
    elements.append(PageBreak())
    return elements


def _section_cash_flow_detail(styles: dict, cash_flow: list) -> list:
    """Appendix — full cash flow table."""
    elements = []
    elements.append(Paragraph("Appendix: Full Cash Flow Projection", styles["SectionHead"]))
    elements.append(_hr())

    table_rows = [["Year", "Age", "Income", "Expenses", "Taxes", "Net CF", "Net Worth"]]
    for r in cash_flow:
        table_rows.append([
            str(r["year"]),
            str(r.get("primary_age", "")),
            _fmt_money(r["income"]),
            _fmt_money(r["expenses"]),
            _fmt_money(r.get("taxes", 0)),
            _fmt_money(r.get("net_cash_flow", 0)),
            _fmt_money(r.get("net_worth", 0)),
        ])

    # Split into chunks of ~25 rows for readability
    chunk_size = 25
    header = table_rows[0]
    data = table_rows[1:]
    for i in range(0, len(data), chunk_size):
        chunk = data[i:i + chunk_size]
        t = _make_table([header] + chunk, col_widths=[
            0.6 * inch, 0.5 * inch, 0.9 * inch, 0.9 * inch,
            0.9 * inch, 0.9 * inch, 1.1 * inch,
        ])
        elements.append(t)
        if i + chunk_size < len(data):
            elements.append(Spacer(1, 0.1 * inch))

    return elements


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_pdf_report(
    planner,
    mc_results: Dict[str, Any],
    cash_flow: List[Dict[str, Any]],
    output_path: str,
    title: Optional[str] = None,
) -> str:
    """Generate a multi-section PDF report.

    Parameters
    ----------
    planner : RetirementPlanner
        The loaded planner instance (has .scenario and .accounts attributes).
    mc_results : dict
        Monte Carlo simulation results.
    cash_flow : list of dict
        Year-by-year cash flow projection.
    output_path : str
        Where to save the PDF.
    title : str, optional
        Override the report title.

    Returns
    -------
    str
        The output_path that was saved to.
    """
    scenario = planner.scenario
    generated_at = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    styles = _styles()

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    elements = []

    # 1. Cover
    elements.extend(_section_cover(styles, scenario, generated_at))

    # 2. Plan Summary
    elements.extend(_section_summary(styles, mc_results, cash_flow))

    # 3. Current Net Worth
    elements.extend(_section_net_worth(styles, list(planner.accounts.values())))

    # 4. Income & Expenses
    elements.extend(_section_income_expenses(styles, cash_flow))

    # 4b. Equity Vesting Timeline
    elements.extend(_section_equity_vesting(styles, planner))

    # 5. Tax Summary
    elements.extend(_section_tax_summary(styles, cash_flow))

    # 6. Monte Carlo
    elements.extend(_section_monte_carlo(styles, mc_results))

    # 7. Net Worth Trajectory
    elements.extend(_section_net_worth_trajectory(styles, cash_flow))

    # 8. Assumptions
    elements.extend(_section_assumptions(styles, scenario))

    # 9. Appendix
    elements.extend(_section_cash_flow_detail(styles, cash_flow))

    doc.build(elements)
    return output_path
