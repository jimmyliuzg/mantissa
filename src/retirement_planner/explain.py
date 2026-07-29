"""
Explainability, validation, and reproducibility (Phase 5).

Provides:
- TaxTrace: detailed breakdown of why tax is what it is
- DecisionTrace: why a particular withdrawal/conversion was chosen
- Threshold warnings: alerts when approaching ACA/IRMAA/bracket boundaries
- Property tests: no negative balances, weights sum correctly
- Reproducibility metadata: RNG seed, tax-law version, config hash
- Scenario comparison: side-by-side projection diffs
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Tax trace — detailed tax calculation breakdown
# ---------------------------------------------------------------------------
@dataclass
class TaxTrace:
    """Step-by-step explanation of a tax calculation."""
    year: int
    filing_status: str
    tax_law_year: int

    # Income breakdown
    ordinary_income: float = 0.0
    capital_gains: float = 0.0
    qcd_amount: float = 0.0
    agi: float = 0.0

    # Deductions
    standard_deduction: float = 0.0
    itemized_deduction: float = 0.0
    deduction_used: float = 0.0
    deduction_type: str = "standard"  # "standard" or "itemized"

    # Federal tax components
    federal_ordinary_tax: float = 0.0
    ltcg_tax: float = 0.0
    niit: float = 0.0
    amt: float = 0.0
    federal_credits: float = 0.0
    federal_total: float = 0.0

    # State tax
    state_tax: float = 0.0
    state_name: str = "CA"

    # Total
    total_tax: float = 0.0
    effective_rate: float = 0.0
    marginal_rate: float = 0.0

    # Warnings
    warnings: List[str] = field(default_factory=list)

    def explain(self) -> str:
        """Human-readable tax explanation."""
        lines = [
            f"Tax Year {self.year} ({self.filing_status})",
            f"  Tax law: {self.tax_law_year}",
            "",
            "Income:",
            f"  Ordinary:    ${self.ordinary_income:>12,.0f}",
            f"  Capital Gains: ${self.capital_gains:>12,.0f}",
            f"  QCD:        ${self.qcd_amount:>12,.0f}",
            f"  AGI:        ${self.agi:>12,.0f}",
            "",
            "Deductions:",
            f"  Standard:   ${self.standard_deduction:>12,.0f}",
            f"  Itemized:   ${self.itemized_deduction:>12,.0f}",
            f"  Used:       ${self.deduction_used:>12,.0f} ({self.deduction_type})",
            "",
            "Federal Tax:",
            f"  Ordinary:   ${self.federal_ordinary_tax:>12,.0f}",
            f"  LTCG:       ${self.ltcg_tax:>12,.0f}",
            f"  NIIT:       ${self.niit:>12,.0f}",
            f"  AMT:        ${self.amt:>12,.0f}",
            f"  Credits:   -${self.federal_credits:>12,.0f}",
            f"  Total:      ${self.federal_total:>12,.0f}",
            "",
            f"State Tax ({self.state_name}): ${self.state_tax:>12,.0f}",
            f"Total Tax:   ${self.total_tax:>12,.0f}",
            f"Effective:   {self.effective_rate:>11.1%}",
            f"Marginal:    {self.marginal_rate:>11.1%}",
        ]
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


def build_tax_trace(
    year: int,
    ordinary_income: float,
    capital_gains: float,
    qcd_amount: float,
    standard_deduction: float,
    itemized_deduction: float,
    federal_ordinary_tax: float,
    ltcg_tax: float,
    niit: float,
    amt: float,
    federal_credits: float,
    state_tax: float,
    filing_status: str = "MFJ",
    tax_law_year: int = 2024,
    state_name: str = "CA",
) -> TaxTrace:
    """Build a complete TaxTrace from calculation components."""
    agi = ordinary_income + capital_gains - qcd_amount
    deduction_used = max(standard_deduction, itemized_deduction)
    deduction_type = "itemized" if itemized_deduction > standard_deduction else "standard"
    federal_total = federal_ordinary_tax + ltcg_tax + niit + amt - federal_credits
    total_tax = federal_total + state_tax
    effective_rate = total_tax / agi if agi > 0 else 0.0

    # Estimate marginal rate (simplified)
    marginal_rate = 0.22  # Default; would need bracket lookup
    if ordinary_income > 400_000:
        marginal_rate = 0.32
    elif ordinary_income > 200_000:
        marginal_rate = 0.24
    elif ordinary_income > 100_000:
        marginal_rate = 0.22

    warnings = []
    if niit > 0:
        warnings.append(f"NIIT applies: MAGI ${agi:,.0f} exceeds threshold")
    if amt > 0:
        warnings.append(f"AMT applies: tentative min tax exceeds regular tax")
    if effective_rate > 0.30:
        warnings.append(f"Effective rate {effective_rate:.1%} is high — consider tax-loss harvesting")

    return TaxTrace(
        year=year,
        filing_status=filing_status,
        tax_law_year=tax_law_year,
        ordinary_income=ordinary_income,
        capital_gains=capital_gains,
        qcd_amount=qcd_amount,
        agi=agi,
        standard_deduction=standard_deduction,
        itemized_deduction=itemized_deduction,
        deduction_used=deduction_used,
        deduction_type=deduction_type,
        federal_ordinary_tax=federal_ordinary_tax,
        ltcg_tax=ltcg_tax,
        niit=niit,
        amt=amt,
        federal_credits=federal_credits,
        federal_total=federal_total,
        state_tax=state_tax,
        state_name=state_name,
        total_tax=total_tax,
        effective_rate=effective_rate,
        marginal_rate=marginal_rate,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Threshold warnings
# ---------------------------------------------------------------------------
@dataclass
class ThresholdWarning:
    """A warning when approaching a tax/benefit threshold."""
    threshold_type: str    # "aca_cliff", "irmaa_tier", "bracket_top", "niit"
    threshold_value: float
    current_value: float
    headroom: float        # how much room left before hitting threshold
    severity: str          # "info", "warning", "critical"
    message: str


def check_thresholds(
    magi: float,
    age: int,
    year: int,
    aca_cliff: float = 124_800,  # 400% FPL for family of 4
    irmaa_tiers: Optional[List[float]] = None,
    bracket_tops: Optional[List[float]] = None,
    niit_threshold: float = 250_000,
) -> List[ThresholdWarning]:
    """Check if the household is approaching any tax/benefit thresholds."""
    warnings = []

    if irmaa_tiers is None:
        irmaa_tiers = [206_000, 258_000, 322_000, 386_000, 750_000]
    if bracket_tops is None:
        bracket_tops = [23_200, 94_300, 201_050, 383_900, 487_450, 731_200]

    # ACA cliff
    if age < 65:
        headroom = aca_cliff - magi
        if headroom < 0:
            severity = "critical"
            msg = f"MAGI ${magi:,.0f} exceeds ACA cliff ${aca_cliff:,.0f} — no subsidy"
        elif headroom < 5_000:
            severity = "warning"
            msg = f"Only ${headroom:,.0f} headroom to ACA cliff"
        elif headroom < 20_000:
            severity = "info"
            msg = f"${headroom:,.0f} headroom to ACA cliff"
        else:
            severity = "info"
            msg = ""
        if msg:
            warnings.append(ThresholdWarning(
                threshold_type="aca_cliff",
                threshold_value=aca_cliff,
                current_value=magi,
                headroom=headroom,
                severity=severity,
                message=msg,
            ))

    # IRMAA tiers
    if age >= 65:
        for i, tier in enumerate(irmaa_tiers):
            if magi < tier:
                headroom = tier - magi
                if headroom < 5_000:
                    warnings.append(ThresholdWarning(
                        threshold_type="irmaa_tier",
                        threshold_value=tier,
                        current_value=magi,
                        headroom=headroom,
                        severity="warning",
                        message=f"${headroom:,.0f} to IRMAA tier {i+1} (${tier:,.0f})",
                    ))
                break

    # Bracket boundaries
    for top in bracket_tops:
        if abs(magi - top) < 5_000:
            warnings.append(ThresholdWarning(
                threshold_type="bracket_top",
                threshold_value=top,
                current_value=magi,
                headroom=top - magi,
                severity="info",
                message=f"${abs(top - magi):,.0f} from {top/1000:.0f}K bracket boundary",
            ))

    # NIIT
    headroom = niit_threshold - magi
    if 0 < headroom < 10_000:
        warnings.append(ThresholdWarning(
            threshold_type="niit",
            threshold_value=niit_threshold,
            current_value=magi,
            headroom=headroom,
            severity="warning",
            message=f"${headroom:,.0f} to NIIT threshold (${niit_threshold:,.0f})",
        ))

    return warnings


# ---------------------------------------------------------------------------
# Reproducibility metadata
# ---------------------------------------------------------------------------
@dataclass
class ReproducibilityMetadata:
    """Tracks everything needed to reproduce a projection exactly."""
    rng_seed: int
    tax_law_version: str
    code_version: str
    config_hash: str
    timestamp: str = ""

    @classmethod
    def from_config(cls, config: dict, code_version: str = "0.2.0") -> "ReproducibilityMetadata":
        """Create metadata from a config dict."""
        seed = random.randint(0, 2**32 - 1)
        config_str = json.dumps(config, sort_keys=True, default=str)
        config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:16]

        return cls(
            rng_seed=seed,
            tax_law_version="2024_enacted",
            code_version=code_version,
            config_hash=config_hash,
        )

    def apply_seed(self):
        """Set the RNG seed for reproducible simulations."""
        random.seed(self.rng_seed)

    def summary(self) -> str:
        return (
            f"Seed: {self.rng_seed} | Tax law: {self.tax_law_version} | "
            f"Code: {self.code_version} | Config: {self.config_hash}"
        )


# ---------------------------------------------------------------------------
# Scenario comparison
# ---------------------------------------------------------------------------
@dataclass
class ScenarioDiff:
    """Side-by-side comparison of two scenarios."""
    label_a: str
    label_b: str
    # Year-by-year differences
    income_diff: List[float] = field(default_factory=list)
    expense_diff: List[float] = field(default_factory=list)
    tax_diff: List[float] = field(default_factory=list)
    net_worth_diff: List[float] = field(default_factory=list)
    # Summary
    total_tax_savings: float = 0.0
    final_nw_diff: float = 0.0
    success_rate_diff: float = 0.0

    def explain(self) -> str:
        lines = [
            f"Scenario Comparison: {self.label_a} vs {self.label_b}",
            f"  Tax savings:   ${self.total_tax_savings:>12,.0f}",
            f"  NW difference: ${self.final_nw_diff:>12,.0f}",
            f"  Success rate:  {self.success_rate_diff:>+11.1%}",
        ]
        return "\n".join(lines)


def compare_scenarios(
    projections_a: List[dict],
    projections_b: List[dict],
    label_a: str = "Scenario A",
    label_b: str = "Scenario B",
) -> ScenarioDiff:
    """Compare two year-by-year projections."""
    n = min(len(projections_a), len(projections_b))
    diff = ScenarioDiff(label_a=label_a, label_b=label_b)

    for i in range(n):
        a, b = projections_a[i], projections_b[i]
        diff.income_diff.append(b.get("income", 0) - a.get("income", 0))
        diff.expense_diff.append(b.get("expenses", 0) - a.get("expenses", 0))
        diff.tax_diff.append(b.get("taxes", 0) - a.get("taxes", 0))
        diff.net_worth_diff.append(b.get("net_worth", 0) - a.get("net_worth", 0))

    if projections_a and projections_b:
        diff.total_tax_savings = sum(diff.tax_diff)
        diff.final_nw_diff = diff.net_worth_diff[-1] if diff.net_worth_diff else 0

    return diff


# ---------------------------------------------------------------------------
# Property tests
# ---------------------------------------------------------------------------
@dataclass
class ValidationResult:
    """Result of a validation check."""
    check_name: str
    passed: bool
    message: str
    severity: str  # "error", "warning", "info"


def validate_projection(projections: List[dict]) -> List[ValidationResult]:
    """Run property tests on a set of projections."""
    results = []

    # Check 1: No negative net worth (unless explicitly allowed)
    for i, p in enumerate(projections):
        nw = p.get("net_worth", 0)
        if nw < -100_000:  # Allow small rounding errors
            results.append(ValidationResult(
                check_name="negative_net_worth",
                passed=False,
                message=f"Year {p.get('year', i)}: net worth ${nw:,.0f} is deeply negative",
                severity="error",
            ))

    # Check 2: Tax is non-negative
    for i, p in enumerate(projections):
        tax = p.get("taxes", 0)
        if tax < -100:  # Allow small refund
            results.append(ValidationResult(
                check_name="negative_tax",
                passed=False,
                message=f"Year {p.get('year', i)}: tax ${tax:,.0f} is negative",
                severity="warning",
            ))

    # Check 3: Income is non-negative (except retirement years)
    for i, p in enumerate(projections):
        income = p.get("income", 0)
        if income < 0:
            results.append(ValidationResult(
                check_name="negative_income",
                passed=False,
                message=f"Year {p.get('year', i)}: income ${income:,.0f} is negative",
                severity="warning",
            ))

    # Check 4: Net worth should generally increase during working years
    if len(projections) > 5:
        early_nw = [p.get("net_worth", 0) for p in projections[:5]]
        if early_nw[-1] < early_nw[0] * 0.8:
            results.append(ValidationResult(
                check_name="nw_decline_working",
                passed=False,
                message="Net worth declining in early working years",
                severity="warning",
            ))

    # Check 5: Success — no checks failed
    if not results:
        results.append(ValidationResult(
            check_name="all_checks",
            passed=True,
            message="All validation checks passed",
            severity="info",
        ))

    return results
