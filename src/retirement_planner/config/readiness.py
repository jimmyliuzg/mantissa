"""Resolve optional shortcuts once, before running annual projections.

Profiles are illustrative assumptions, not forecasts. Explicit account yields
always override a profile. No UI or simulator maintains a second default table.
"""
from copy import deepcopy
from ..models import ACCOUNT_TAX_DEFAULTS

INCOME_PROFILES = {
    "none": (0.0, 0.0, 0.0, 0.0),
    "stock_index": (0.0, 0.02, 0.9, 0.0),
    "balanced": (0.015, 0.015, 0.8, 0.0),
    "income": (0.04, 0.01, 0.5, 0.0),
    "cash": (0.03, 0.0, 0.0, 0.0),
}
YIELD_FIELDS = ("interest_yield", "dividend_yield", "qualified_dividend_share", "capital_gain_yield")


def resolve_inputs(config):
    """Return an independent config plus a value-free readiness report."""
    resolved = deepcopy(config)
    metadata = config.get("input_metadata", {})
    estimates = set(metadata.get("estimated_fields", []))
    items = []

    def record(path, present, detail):
        status = "estimated" if path in estimates else "provided" if present else "missing"
        items.append({"path": path, "status": status, "detail": detail})

    aggregate = metadata.get("account_breakdown") == "missing"
    record("accounts", not aggregate, "Separate taxable, traditional and Roth balances to assess account access.")
    record("balance_date", bool(config.get("balance_date")), "Confirm the statement date; balances are carried unchanged to the opening year.")
    for i, account in enumerate(resolved.get("accounts", [])):
        path = f"accounts[{i}]"
        kind = account.get("type")
        tax = account.get("tax_treatment", ACCOUNT_TAX_DEFAULTS.get(kind, "taxable"))
        if account.get("cost_basis") is None and "unrealized_gain_fraction" in account:
            account["cost_basis"] = account["balance"] * (1 - account["unrealized_gain_fraction"])
            estimates.add(path + ".cost_basis")
        if tax == "taxable" and kind not in {"cash", "checking", "savings", "money_market", "real_estate", "vehicle"}:
            record(path + ".cost_basis", account.get("cost_basis") is not None,
                   "Missing taxable basis uses opening value and can understate gains on sales.")
        if tax == "roth":
            record(path + ".roth_contribution_basis", "roth_contribution_basis" in account,
                   "Missing Roth contribution principal is treated as zero for access.")
            record(path + ".roth_first_contribution_year", account.get("roth_first_contribution_year") is not None,
                   "Confirm the first Roth contribution year to assess the five-year clock.")
        if tax != "taxable" or kind in {"real_estate", "vehicle"}:
            continue
        profile = account.get("investment_income_profile")
        if profile is not None:
            for field, value in zip(YIELD_FIELDS, INCOME_PROFILES[profile]):
                if field not in account:
                    account[field] = value
                    items.append({"path": path + "." + field, "status": "estimated",
                                  "detail": f"Illustrative {profile} profile assumes {value:.1%} for this field; replace with your expected value."})
                else:
                    record(path + "." + field, True, "Explicit input overrides the income profile.")
            if profile == "cash" and "growth_rate" not in account:
                inflation = config.get("economic", {}).get("inflation", 0.025)
                account["growth_rate"] = (1 + account["interest_yield"] + account["dividend_yield"]) / (1 + inflation) - 1
                items.append({"path": path + ".growth_rate", "status": "estimated", "detail": "Cash profile total return follows its nominal yield less general inflation."})
        else:
            for field in ("interest_yield", "dividend_yield", "capital_gain_yield"):
                record(path + "." + field, field in account,
                       "Unspecified investment yields remain zero; confirm expected annual distributions.")
            if account.get("dividend_yield", 0) > 0 or "qualified_dividend_share" in account:
                record(path + ".qualified_dividend_share", "qualified_dividend_share" in account,
                       "Unspecified qualified dividend share is zero.")
    # Retain estimates of age/retirement anchors and other UI approximations.
    known = {item["path"] for item in items}
    for path in sorted(estimates - known):
        items.append({"path": path, "status": "estimated", "detail": "Estimated during onboarding; refine in the plan editor."})
    return resolved, {"provisional": any(i["status"] != "provided" for i in items),
                      "access_assessed": not aggregate, "items": items}
