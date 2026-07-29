"""
Shared formatting utilities — eliminates duplicate _fmt_money across modules.
"""


def fmt_money(value: float) -> str:
    """Format a float as $X,XXX,XXX."""
    return f"${value:,.0f}"


def fmt_money_millions(value: float) -> str:
    """Format as $X.XM for large numbers, $X,XXX for smaller."""
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:,.1f}M"
    return f"${value:,.0f}"


def fmt_pct(value: float) -> str:
    """Format as X.X%."""
    return f"{value:.1%}"
