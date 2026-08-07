"""
Approximation and warning metadata for projections (Phase 3.4).

Every projection should be able to report material simplifications
so that users understand what the model does and doesn't capture.

Approximation categories:
- AGGREGATE_BASIS: Taxable account uses aggregate cost basis, not tax lots.
- SIMPLIFIED_DETERMINISTIC_TAXES: Deterministic mode uses simplified tax calc.
- HISTORICAL_BOND_DATA: Bond returns modeled from historical data.
- SIMPLIFIED_AMT: AMT treatment is approximate.
- SIMPLIFIED_ESTATE_TAX: Estate tax is simplified (unified credit only).
- EXPERIMENTAL_OPTIMIZER: Optimizer recommendations are not decision-safe.
- DETERMINISTIC_RETURNS: Investment returns use fixed rates, not stochastic.
- SOCIAL_SECURITY_MODELING: SS benefits use simplified claiming model.
- HEALTHCARE_INFLATION: Healthcare costs use a single inflation rate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ApproximationCategory(str, Enum):
    """Categories of model approximations and simplifications."""
    AGGREGATE_BASIS = "aggregate_basis"
    SIMPLIFIED_DETERMINISTIC_TAXES = "simplified_deterministic_taxes"
    HISTORICAL_BOND_DATA = "historical_bond_data"
    SIMPLIFIED_AMT = "simplified_amt"
    SIMPLIFIED_ESTATE_TAX = "simplified_estate_tax"
    EXPERIMENTAL_OPTIMIZER = "experimental_optimizer"
    DETERMINISTIC_RETURNS = "deterministic_returns"
    SOCIAL_SECURITY_MODELING = "social_security_modeling"
    HEALTHCARE_INFLATION = "healthcare_inflation"


@dataclass
class ApproximationWarning:
    """A material approximation or simplification in a projection.

    Attributes:
        category: The type of approximation.
        message: Human-readable description of the approximation.
        severity: How material the approximation is.
            "info" — minor, unlikely to affect decisions.
            "warning" — moderate, may affect decisions in edge cases.
            "critical" — significant, could materially change recommendations.
        source: Where the approximation originates (module, function, etc.).
        year: The projection year this applies to (None = all years).
    """
    category: ApproximationCategory
    message: str
    severity: str = "warning"  # "info", "warning", "critical"
    source: str = ""
    year: Optional[int] = None

    def as_dict(self) -> dict:
        d = {
            "category": self.category.value,
            "message": self.message,
            "severity": self.severity,
        }
        if self.source:
            d["source"] = self.source
        if self.year is not None:
            d["year"] = self.year
        return d

    def __str__(self) -> str:
        prefix = f"[{self.severity.upper()}]" if self.severity != "info" else "[INFO]"
        loc = f" (year {self.year})" if self.year is not None else ""
        return f"{prefix} {self.category.value}{loc}: {self.message}"


# ---------------------------------------------------------------------------
# Pre-defined approximation warnings used by the engine
# ---------------------------------------------------------------------------

AGGREGATE_BASIS_WARNING = ApproximationWarning(
    category=ApproximationCategory.AGGREGATE_BASIS,
    message=(
        "Taxable accounts use aggregate cost basis, not individual tax lots. "
        "Capital gains are estimated from aggregate basis rather than "
        "lot-specific identification."
    ),
    severity="warning",
    source="engine.project_cash_flow",
)

DETERMINISTIC_TAXES_WARNING = ApproximationWarning(
    category=ApproximationCategory.SIMPLIFIED_DETERMINISTIC_TAXES,
    message=(
        "Deterministic projections use simplified tax calculations. "
        "Income is treated as fully ordinary; capital gains routing "
        "and bracket interactions may differ from actual tax filing."
    ),
    severity="warning",
    source="engine.project_cash_flow",
)

EXPERIMENTAL_OPTIMIZER_WARNING = ApproximationWarning(
    category=ApproximationCategory.EXPERIMENTAL_OPTIMIZER,
    message=(
        "Optimizer recommendations are experimental. Withdrawal and "
        "conversion decisions should be reviewed by a qualified advisor."
    ),
    severity="critical",
    source="optimizer",
)

DETERMINISTIC_RETURNS_WARNING = ApproximationWarning(
    category=ApproximationCategory.DETERMINISTIC_RETURNS,
    message=(
        "Deterministic projections use fixed return rates. Actual returns "
        "will vary; Monte Carlo simulation provides a more realistic "
        "range of outcomes."
    ),
    severity="info",
    source="engine.project_cash_flow",
)


@dataclass
class ApproximationTracker:
    """Collects approximation warnings across a projection run.

    Deduplicates by (category, year) to avoid flooding the output
    with repeated messages.
    """
    warnings: List[ApproximationWarning] = field(default_factory=list)
    _seen: set = field(default_factory=set, repr=False)

    def add(self, warning: ApproximationWarning) -> None:
        """Add a warning if not already seen (by category + year)."""
        key = (warning.category, warning.year)
        if key not in self._seen:
            self._seen.add(key)
            self.warnings.append(warning)

    def add_all(self, warnings: List[ApproximationWarning]) -> None:
        """Add multiple warnings."""
        for w in warnings:
            self.add(w)

    def for_year(self, year: int) -> List[ApproximationWarning]:
        """Return warnings applicable to a specific year."""
        return [w for w in self.warnings if w.year is None or w.year == year]

    def by_severity(self, severity: str) -> List[ApproximationWarning]:
        """Return warnings of a given severity level."""
        return [w for w in self.warnings if w.severity == severity]

    def has_critical(self) -> bool:
        """Check if any critical approximations exist."""
        return any(w.severity == "critical" for w in self.warnings)

    def summary(self) -> str:
        """Human-readable summary of all approximations."""
        if not self.warnings:
            return "No approximations recorded."
        lines = [f"Approximations ({len(self.warnings)} total):"]
        for w in self.warnings:
            lines.append(f"  {w}")
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "count": len(self.warnings),
            "warnings": [w.as_dict() for w in self.warnings],
        }
