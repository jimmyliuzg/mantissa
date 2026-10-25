"""Goal outcomes derived from the shared annual funding path.

This module does not change cash flows or run a counterfactual budget. A planned
budget is met only when the actual path funded it without reductions above the
one-base-year-dollar reporting tolerance. Legacy attainment is independent.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OutcomeTracker:
    access_assessed: bool
    first_funding_shortfall_year: Optional[int] = None
    first_funding_shortfall_causes: list = field(default_factory=list)
    first_spending_cut_year: Optional[int] = None
    access_gap: bool = False

    def observe(self, year, cash_gap, access_gap, capital_gap, housing_gap,
                spending_cut, tolerance):
        funding_gap = cash_gap + housing_gap
        funded = bool(funding_gap <= tolerance)
        cut = bool(spending_cut > tolerance)
        causes = []
        if not funded:
            if access_gap > tolerance:
                causes.append("account_access" if self.access_assessed else "unassessed_access")
            if capital_gap > tolerance:
                causes.append("liquid_capital")
            if housing_gap > tolerance:
                causes.append("housing_purchase")
            if not causes:
                causes.append("funding_gap")
            if self.first_funding_shortfall_year is None:
                self.first_funding_shortfall_year = year
                self.first_funding_shortfall_causes = causes
        if access_gap > tolerance:
            self.access_gap = True
        if cut and self.first_spending_cut_year is None:
            self.first_spending_cut_year = year
        return {"funding_shortfall": funding_gap,
                "housing_funding_shortfall": housing_gap,
                "funding_shortfall_causes": causes,
                "adjusted_spending_met": funded,
                "planned_spending_met": funded and not cut,
                "account_access_met": not (access_gap > tolerance) if self.access_assessed else None}

    def finish(self, final_after_estate, legacy_target):
        funded = self.first_funding_shortfall_year is None
        return {"schema_version": 1,
                "planned_spending_met": funded and self.first_spending_cut_year is None,
                "adjusted_spending_met": funded,
                "account_access_met": not self.access_gap if self.access_assessed else None,
                "legacy_target_met": bool(final_after_estate >= legacy_target),
                "legacy_target": legacy_target,
                "legacy_shortfall": max(0.0, legacy_target - final_after_estate),
                "first_funding_shortfall_year": self.first_funding_shortfall_year,
                "first_funding_shortfall_causes": list(self.first_funding_shortfall_causes),
                "first_spending_cut_year": self.first_spending_cut_year}


def aggregate_outcomes(results, base_year, convention, legacy_target):
    """All rates use every run; access uses only assessed runs, or is null."""
    outcomes = [r["outcomes"] for r in results]
    count = len(outcomes)
    assessed = [r for r in outcomes if r["account_access_met"] is not None]
    years = {}
    causes = {}
    for result in outcomes:
        year = result["first_funding_shortfall_year"]
        if year is not None:
            key = str(year)
            years[key] = years.get(key, 0) + 1
            for cause in result["first_funding_shortfall_causes"]:
                causes[cause] = causes.get(cause, 0) + 1
    return {"schema_version": 1,
            "planned_spending_met_rate": sum(r["planned_spending_met"] for r in outcomes) / count,
            "adjusted_spending_met_rate": sum(r["adjusted_spending_met"] for r in outcomes) / count,
            "account_access_met_rate": sum(r["account_access_met"] for r in assessed) / len(assessed) if assessed else None,
            "legacy_target_met_rate": sum(r["legacy_target_met"] for r in outcomes) / count,
            "terminal_estate_estimate_runs": sum(r["estate_tax_timing"] == "terminal_estimate" for r in outcomes),
            "denominators": {"spending": count, "account_access": len(assessed), "legacy": count},
            "base_year": base_year, "monetary_convention": convention,
            "legacy_target_base_year": legacy_target,
            "first_funding_shortfall_year_counts": dict(sorted(years.items())),
            "first_funding_shortfall_cause_counts": dict(sorted(causes.items()))}
