"""Schema-aware validation for Mantissa JSON configurations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
from typing import Any, Dict, Iterable, List, Optional

from ..models import ACCOUNT_TAX_DEFAULTS

CURRENT_SCHEMA_VERSION = 1


@dataclass
class ValidationIssue:
    path: str
    message: str
    severity: str = "error"
    code: str = "invalid"

    def as_dict(self) -> dict:
        return {"path": self.path, "message": self.message,
                "severity": self.severity, "code": self.code}


@dataclass
class ValidationResult:
    issues: List[ValidationIssue] = field(default_factory=list)
    schema_version: int = CURRENT_SCHEMA_VERSION

    @property
    def errors(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"valid": self.valid, "schema_version": self.schema_version,
                "errors": [i.as_dict() for i in self.errors],
                "warnings": [i.as_dict() for i in self.warnings]}

    def raise_for_errors(self) -> None:
        if self.errors:
            details = "; ".join(f"{i.path}: {i.message}" for i in self.errors)
            raise ValueError(details)


_SCHEMA_KEYS = {
    "name", "description", "schema_version", "primary", "spouse",
    "economic", "accounts", "income_streams", "expenses", "mortgages",
    "windfalls", "housing_events", "roth_conversions", "rollover_events",
    "age_events", "dependents",
    "social_security", "glidepath", "withdrawal_strategy", "withdrawal_rate",
    "guardrail_floor_pct", "guardrail_ceiling_pct", "legacy_goal", "state",
    "family_size", "savings_order", "surplus_account_id", "monetary_convention", "stress_level",
    "input_metadata", "survivor_expense_ratio", "_comment", "start_year", "balance_date", "tax_inputs", "withdrawal_access_policy",
}


def _issue(result, path, message, severity="error", code="invalid"):
    result.issues.append(ValidationIssue(path, message, severity, code))


def _number(result, value, path, low=None, high=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _issue(result, path, "must be a number", code="type")
        return
    if not math.isfinite(value):
        _issue(result, path, "must be finite", code="range")
        return
    if low is not None and value < low:
        _issue(result, path, f"must be >= {low}", code="range")
    if high is not None and value > high:
        _issue(result, path, f"must be <= {high}", code="range")


def _date(result, value, path):
    if not isinstance(value, str):
        _issue(result, path, "must be an ISO date (YYYY-MM-DD)", code="date")
        return
    try:
        date.fromisoformat(value)
    except ValueError:
        _issue(result, path, "must be an ISO date (YYYY-MM-DD)", code="date")


def validate_config(config: dict, strict: bool = False) -> ValidationResult:
    """Validate raw config and return structured errors and warnings."""
    result = ValidationResult()
    if not isinstance(config, dict):
        _issue(result, "$", "configuration must be an object", code="type")
        return result

    version = config.get("schema_version", CURRENT_SCHEMA_VERSION)
    if not isinstance(version, int):
        _issue(result, "$.schema_version", "must be an integer", code="type")
    elif version != CURRENT_SCHEMA_VERSION:
        _issue(result, "$.schema_version", f"unsupported schema version {version}", code="version")
        result.schema_version = version

    unknown = sorted(set(config) - _SCHEMA_KEYS)
    for key in unknown:
        _issue(result, f"$.{key}", "unknown configuration key", "error" if strict else "warning", "unknown_key")

    for key in ("primary", "spouse"):
        person = config.get(key)
        # `spouse` is optional (issue #3): a missing or null value
        # means a single-household plan. `primary` is still required.
        if key == "spouse" and person is None:
            if "spouse" in config and config["spouse"] is not None:
                pass  # fall through to the dict check below for {} etc.
            else:
                continue
        if not isinstance(person, dict):
            _issue(result, f"$.{key}", "required object", code="required")
            continue
        for field_name in ("name", "birth_date", "retirement_date"):
            if field_name not in person:
                _issue(result, f"$.{key}.{field_name}", "required field", code="required")
        if "birth_date" in person:
            _date(result, person["birth_date"], f"$.{key}.birth_date")
        if "retirement_date" in person:
            _date(result, person["retirement_date"], f"$.{key}.retirement_date")
        if "longevity_age" in person:
            _number(result, person["longevity_age"], f"$.{key}.longevity_age", 0, 130)

    if config.get("withdrawal_access_policy", "penalty_free") not in {"penalty_free", "unrestricted"}:
        _issue(result, "$.withdrawal_access_policy", "must be penalty_free or unrestricted")

    metadata = config.get("input_metadata", {})
    if not isinstance(metadata, dict):
        _issue(result, "$.input_metadata", "must be an object")
    else:
        if metadata.get("account_breakdown", "provided") not in {"provided", "missing"}:
            _issue(result, "$.input_metadata.account_breakdown", "must be provided or missing")
        estimates = metadata.get("estimated_fields", [])
        if not isinstance(estimates, list) or any(not isinstance(p, str) for p in estimates):
            _issue(result, "$.input_metadata.estimated_fields", "must be an array of field paths")

    accounts = config.get("accounts", [])
    if not isinstance(accounts, list):
        _issue(result, "$.accounts", "must be an array", code="type")
        accounts = []
    ids = set()
    valid_owners = {"primary", "spouse"}
    for index, account in enumerate(accounts):
        path = f"$.accounts[{index}]"
        if not isinstance(account, dict):
            _issue(result, path, "must be an object", code="type")
            continue
        aid = account.get("id")
        if not aid:
            _issue(result, f"{path}.id", "required field", code="required")
        elif aid in ids:
            _issue(result, f"{path}.id", f"duplicate account id '{aid}'", code="duplicate")
        else:
            ids.add(aid)
        for field_name in ("name", "type", "balance"):
            if field_name not in account:
                _issue(result, f"{path}.{field_name}", "required field", code="required")
        from .readiness import INCOME_PROFILES
        profile = account.get("investment_income_profile")
        if profile is not None and (not isinstance(profile, str) or profile not in INCOME_PROFILES):
            _issue(result, path + ".investment_income_profile", "unsupported income profile")
        for field in ("interest_yield", "dividend_yield", "qualified_dividend_share", "unrealized_gain_fraction", "capital_gain_yield"):
            if field in account:
                _number(result, account[field], path + "." + field, 0, 1)
        if all(isinstance(account.get(f, 0), (int, float)) for f in ("interest_yield", "dividend_yield", "capital_gain_yield")) and sum(account.get(f, 0) for f in ("interest_yield", "dividend_yield", "capital_gain_yield")) > 1:
            _issue(result, path, "combined distribution yield must not exceed 1")
        if "reinvest_distributions" in account and not isinstance(account["reinvest_distributions"], bool):
            _issue(result, path + ".reinvest_distributions", "must be a boolean")
        expected = ACCOUNT_TAX_DEFAULTS.get(account.get("type"))
        declared = account.get("tax_treatment", expected)
        if expected and declared != expected and not (account.get("type") == "401k" and declared == "roth"):
            _issue(result, f"{path}.tax_treatment", "conflicts with retirement account type")
        if "balance" in account:
            _number(result, account["balance"], f"{path}.balance", 0)
        if "owner" in account and account["owner"] not in valid_owners:
            _issue(result, f"{path}.owner", "must be 'primary' or 'spouse'", code="reference")
        for field_name in ("growth_rate", "expense_ratio"):
            if field_name in account:
                _number(result, account[field_name], f"{path}.{field_name}", -1, 10)
        if "equity_pct" in account:
            _number(result, account["equity_pct"], f"{path}.equity_pct", 0, 1)

    opening_year = config.get("start_year", date.today().year)
    if not isinstance(opening_year, int):
        opening_year = date.today().year
    for index, account in enumerate(accounts):
        if not isinstance(account, dict):
            continue
        path = f"$.accounts[{index}]"
        if "roth_contribution_basis" in account:
            _number(result, account["roth_contribution_basis"], path + ".roth_contribution_basis", 0)
        first_year = account.get("roth_first_contribution_year")
        if first_year is not None and (not isinstance(first_year, int) or isinstance(first_year, bool) or not 1900 <= first_year <= opening_year):
            _issue(result, path + ".roth_first_contribution_year", "must be an integer no later than the opening year")
        cohorts = account.get("roth_conversion_basis", [])
        if not isinstance(cohorts, list):
            _issue(result, path + ".roth_conversion_basis", "must be an array")
            continue
        for j, cohort in enumerate(cohorts):
            cp = path + f".roth_conversion_basis[{j}]"
            if not isinstance(cohort, dict):
                _issue(result, cp, "must be an object")
                continue
            y = cohort.get("year")
            if not isinstance(y, int) or isinstance(y, bool) or not 1900 <= y <= opening_year:
                _issue(result, cp + ".year", "must be an integer no later than the opening year")
            elif isinstance(first_year, int) and first_year > y:
                _issue(result, cp + ".year", "precedes declared first Roth contribution year")
            _number(result, cohort.get("amount"), cp + ".amount", 0)
        if (account.get("roth_contribution_basis", 0) or cohorts) and account.get("type") != "roth_ira":
            _issue(result, path, "declared Roth IRA principal requires type roth_ira")

    destination_id = config.get("surplus_account_id")
    if destination_id is not None:
        destination = next((a for a in config.get("accounts", []) if isinstance(a, dict) and a.get("id") == destination_id), None)
        if not isinstance(destination_id, str) or destination is None:
            _issue(result, "$.surplus_account_id", "must reference an existing account", code="reference")
        elif destination.get("liquid", True) is not True or destination.get("tax_treatment", ACCOUNT_TAX_DEFAULTS.get(destination.get("type"), "taxable")) != "taxable" or destination.get("type") in {"real_estate", "vehicle", "hsa", "529"}:
            _issue(result, "$.surplus_account_id", "must be a liquid unrestricted taxable account")

    for index, account_id in enumerate(config.get("savings_order", [])):
        if account_id not in ids:
            _issue(result, f"$.savings_order[{index}]", f"unknown account '{account_id}'", code="reference")

    for index, dep in enumerate(config.get("dependents", [])):
        path = f"$.dependents[{index}]"
        if not isinstance(dep, dict):
            _issue(result, path, "must be an object", code="type")
            continue
        if "birth_date" not in dep:
            _issue(result, f"{path}.birth_date", "required field", code="required")
        else:
            _date(result, dep["birth_date"], f"{path}.birth_date")

    for index, wf in enumerate(config.get("windfalls", [])):
        path = f"$.windfalls[{index}]"
        if not isinstance(wf, dict):
            continue
        for field in ("goes_to_account", "source_account"):
            acct = wf.get(field)
            if acct and acct not in ids:
                _issue(result, f"{path}.{field}",
                       f"unknown account '{acct}'", code="reference")

    for key, events in (("roth_conversions", "start_date"),
                        ("rollover_events", "event_date")):
        for index, ev in enumerate(config.get(key, [])):
            path = f"$.{key}[{index}]"
            if not isinstance(ev, dict):
                _issue(result, path, "must be an object", code="type")
                continue
            if ev.get("source_account") not in ids:
                _issue(result, f"{path}.source_account",
                       f"unknown account '{ev.get('source_account')}'", code="reference")
            if ev.get("target_account") not in ids:
                _issue(result, f"{path}.target_account",
                       f"unknown account '{ev.get('target_account')}'", code="reference")
            if key == "rollover_events":
                _date(result, ev.get("event_date"), f"{path}.event_date")

    account_map = {a.get("id"): {**a, "tax_treatment": a.get("tax_treatment", ACCOUNT_TAX_DEFAULTS.get(a.get("type"), "taxable"))} for a in accounts if isinstance(a, dict)}
    for index, expense in enumerate(config.get("expenses", [])):
        if not isinstance(expense, dict):
            continue
        path = f"$.expenses[{index}]"
        if "hsa_qualified" in expense and not isinstance(expense["hsa_qualified"], bool):
            _issue(result, path + ".hsa_qualified", "must be a boolean")
        funding = account_map.get(expense.get("funding_account"), {})
        if funding.get("type") == "hsa" and not expense.get("hsa_qualified", False):
            _issue(result, path + ".hsa_qualified", "HSA funding requires an explicit qualified-expense assertion")
        if funding.get("tax_treatment") in {"pre_tax", "roth"}:
            _issue(result, path + ".funding_account", "retirement distributions must use the withdrawal/access engine")
    for key in ("windfalls", "housing_events"):
        for index, event in enumerate(config.get(key, [])):
            if not isinstance(event, dict):
                continue
            field = "source_account" if key == "windfalls" else "funding_account"
            funding = account_map.get(event.get(field), {})
            if funding.get("tax_treatment") in {"pre_tax", "roth"} or funding.get("type") in {"hsa", "529"}:
                _issue(result, f"$.{key}[{index}].{field}", "restricted-account access cannot be bypassed by this event")

    glidepath = config.get("glidepath")
    if glidepath is not None:
        if not isinstance(glidepath, dict):
            _issue(result, "$.glidepath", "must be an object", code="type")
        else:
            anchors = glidepath.get("equity_by_age", {})
            if not isinstance(anchors, dict) or not anchors:
                _issue(result, "$.glidepath.equity_by_age", "must contain age anchors", code="required")
            else:
                for age, value in anchors.items():
                    try:
                        int_age = int(age)
                    except (TypeError, ValueError):
                        _issue(result, "$.glidepath.equity_by_age", f"invalid age '{age}'", code="type")
                        continue
                    _number(result, value, f"$.glidepath.equity_by_age.{age}", 0, 1)
                    if int_age < 0:
                        _issue(result, f"$.glidepath.equity_by_age.{age}", "age must be non-negative", code="range")
            for key in ("pre_retirement_years", "post_retirement_years", "tent_ramp_years"):
                if key in glidepath:
                    _number(result, glidepath[key], f"$.glidepath.{key}", 0)
            if "tent_equity_pct" in glidepath:
                _number(result, glidepath["tent_equity_pct"], "$.glidepath.tent_equity_pct", 0, 1)

    convention = config.get("monetary_convention")
    if convention is not None and convention not in ("real", "nominal"):
        _issue(result, "$.monetary_convention", "must be 'real' or 'nominal'", code="enum")
    if "stress_level" in config:
        _number(result, config["stress_level"], "$.stress_level", 0, 1)
    if "survivor_expense_ratio" in config:
        _number(result, config["survivor_expense_ratio"], "$.survivor_expense_ratio", 0, 1)

    # Issue #1: `withdrawal_rate` is consulted only by the
    # `percent_of_portfolio` and `floor_ceiling` strategies. When set
    # under any other strategy (including the default `fixed`), the
    # value has no effect. Surface this as a warning so users don't
    # silently edit a value that doesn't do anything.
    if "withdrawal_rate" in config:
        strategy = config.get("withdrawal_strategy", "fixed")
        if strategy not in ("percent_of_portfolio", "floor_ceiling"):
            _issue(
                result,
                "$.withdrawal_rate",
                (
                    f"withdrawal_rate is set but withdrawal_strategy is "
                    f"'{strategy}'; this field is only consulted under "
                    f"'percent_of_portfolio' or 'floor_ceiling'."
                ),
                severity="warning",
                code="unused_field",
            )

    if "start_year" in config:
        value = config["start_year"]
        if not isinstance(value, int) or isinstance(value, bool) or not 2024 <= value <= 2200:
            _issue(result, "$.start_year", "must be an integer year from 2024 to 2200")
    if config.get("balance_date") is not None:
        _date(result, config["balance_date"], "$.balance_date")
    economic = config.get("economic", {})
    if isinstance(economic, dict):
        if "bond_return_volatility" in economic:
            _number(result, economic["bond_return_volatility"], "$.economic.bond_return_volatility", 0, 1)
        if "equity_bond_correlation" in economic:
            _number(result, economic["equity_bond_correlation"], "$.economic.equity_bond_correlation", -1, 1)
    account_map = {a.get("id"): a for a in accounts if isinstance(a, dict)}
    for i, a in enumerate(accounts):
        if not isinstance(a, dict):
            continue
        path = f"$.accounts[{i}]"
        if a.get("asset_class") not in (None, "cash", "equity", "bond", "mixed"):
            _issue(result, path + ".asset_class", "must be cash, equity, bond or mixed")
        for key in ("cost_basis", "return_volatility", "annual_contribution_cap"):
            if a.get(key) is not None:
                _number(result, a[key], path + "." + key, 0)
        if a.get("contribution_end_date"):
            _date(result, a["contribution_end_date"], path + ".contribution_end_date")
        caps = a.get("contribution_caps_by_year", {})
        if not isinstance(caps, dict):
            _issue(result, path + ".contribution_caps_by_year", "must be an object")
        else:
            for year, cap in caps.items():
                if not str(year).isdigit():
                    _issue(result, path + ".contribution_caps_by_year", "keys must be calendar years")
                _number(result, cap, path + f".contribution_caps_by_year.{year}", 0)
    for key in ("roth_conversions", "rollover_events"):
        for i, ev in enumerate(config.get(key, [])):
            if not isinstance(ev, dict):
                continue
            source = account_map.get(ev.get("source_account"), {})
            target = account_map.get(ev.get("target_account"), {})
            if source and target:
                if ev.get("source_account") == ev.get("target_account"):
                    _issue(result, f"$.{key}[{i}]", "source and target must differ")
                if source.get("owner", "primary") != target.get("owner", "primary"):
                    _issue(result, f"$.{key}[{i}]", "retirement transfers must stay with the same owner")
                if source.get("tax_treatment", "taxable") != "pre_tax":
                    _issue(result, f"$.{key}[{i}]", "source must be pre-tax")
                expected = "roth" if key == "roth_conversions" else "pre_tax"
                if target.get("tax_treatment", "taxable") != expected:
                    _issue(result, f"$.{key}[{i}]", f"target must be {expected}")
    allowed_tax = {"salt_paid", "charitable_deductions", "mortgage_interest", "ca_mortgage_interest", "ca_property_tax", "ca_income_adjustment", "charitable_limit_pct", "qcd_amount"}
    tax_inputs = config.get("tax_inputs", {})
    if not isinstance(tax_inputs, dict):
        _issue(result, "$.tax_inputs", "must be an object keyed by calendar year")
    else:
        for year, fields in tax_inputs.items():
            if not str(year).isdigit() or not isinstance(fields, dict):
                _issue(result, "$.tax_inputs", "each calendar year must contain an object")
                continue
            for key, value in fields.items():
                if key not in allowed_tax:
                    _issue(result, f"$.tax_inputs.{year}.{key}", "unsupported tax input")
                else:
                    _number(result, value, f"$.tax_inputs.{year}.{key}", None if key == "ca_income_adjustment" else 0, 1 if key == "charitable_limit_pct" else None)
    for key in ("expenses", "mortgages", "windfalls", "housing_events"):
        for i, item in enumerate(config.get(key, [])):
            if not isinstance(item, dict):
                continue
            path = f"$.{key}[{i}]"
            for field in ("funding_account",):
                if item.get(field) and item[field] not in ids:
                    _issue(result, path + "." + field, "unknown funding account")
            if key == "expenses":
                if item.get("payment_kind", "cash") not in {"cash", "in_kind"}:
                    _issue(result, path + ".payment_kind", "must be cash or in_kind")
                if item.get("payment_kind") == "in_kind" and not item.get("funding_account"):
                    _issue(result, path, "in-kind gifts need a funding account")
            if key == "windfalls":
                if item.get("wage_owner") not in (None, "primary", "spouse"):
                    _issue(result, path + ".wage_owner", "must be primary or spouse")
                if item.get("taxable_kind", "ordinary") not in {"ordinary", "capital_gains"}:
                    _issue(result, path + ".taxable_kind", "must be ordinary or capital_gains")
                if item.get("taxable_amount") is not None:
                    _number(result, item["taxable_amount"], path + ".taxable_amount", 0)
            if key in {"mortgages", "housing_events"}:
                for field in ("deductible_debt_limit", "ca_deductible_debt_limit"):
                    if field in item:
                        _number(result, item[field], path + "." + field, 0)
            if key == "mortgages":
                if item.get("deduction_kind", "none") not in {"none", "itemized", "rental"}:
                    _issue(result, path + ".deduction_kind", "must be none, itemized or rental")
                changes = item.get("rate_changes", [])
                if not isinstance(changes, list):
                    _issue(result, path + ".rate_changes", "must be an array")
                else:
                    for j, change in enumerate(changes):
                        if not isinstance(change, dict):
                            _issue(result, path + ".rate_changes", "each change must be an object")
                            continue
                        _date(result, change.get("date"), path + f".rate_changes[{j}].date")
                        for field in ("interest_rate", "monthly_payment"):
                            if field in change:
                                _number(result, change[field], path + f".rate_changes[{j}].{field}", 0, 1 if field == "interest_rate" else None)
            if key == "housing_events":
                if item.get("mortgage_deduction_kind", "none") not in {"none", "itemized", "rental"}:
                    _issue(result, path + ".mortgage_deduction_kind", "must be none, itemized or rental")
                for field in ("selling_costs", "purchase_costs"):
                    if field in item:
                        _number(result, item[field], path + "." + field, 0)
                if item.get("mortgage_amount", 0) > item.get("purchase_price", 0):
                    _issue(result, path, "mortgage cannot exceed purchase price")
    return result


def schema_dict() -> dict:
    """Return the supported, intentionally permissive v1 JSON schema."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/jimmyliuzg/mantissa/schema/v1.json",
        "title": "Mantissa Retirement Scenario",
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "schema_version": {"type": "integer", "const": CURRENT_SCHEMA_VERSION},
            "name": {"type": "string"}, "description": {"type": "string"},
            "primary": {"$ref": "#/$defs/person"},
            "spouse": {"anyOf": [{"$ref": "#/$defs/person"}, {"type": "null"}]},
            "accounts": {"type": "array", "items": {"$ref": "#/$defs/account"}},
            "monetary_convention": {"enum": ["real", "nominal"]},
            "withdrawal_access_policy": {"enum": ["penalty_free", "unrestricted"]},
            "start_year": {"type": "integer", "minimum":2024, "maximum":2200},
            "balance_date": {"type":"string", "format":"date"},
            "tax_inputs": {"type":"object"},
            "input_metadata": {"type":"object"},
            "surplus_account_id": {"type":["string", "null"], "description":"Liquid unrestricted taxable account receiving post-contribution cash surplus."},
        },
        "required": ["primary"],
        "$defs": {
            "person": {"type": "object", "required": ["name", "birth_date", "retirement_date"]},
            "account": {"type": "object", "required": ["id", "name", "type", "balance"],
                        "properties": {
                            "roth_contribution_basis": {"type": "number", "minimum": 0},
                            "roth_first_contribution_year": {"type": ["integer", "null"]},
                            "roth_conversion_basis": {"type": "array", "items": {"type": "object", "required": ["year", "amount"], "properties": {"year": {"type": "integer"}, "amount": {"type": "number", "minimum": 0}}}},
                            "asset_class": {"enum":["cash", "equity", "bond", "mixed", None]},
                            "cost_basis": {"type":["number", "null"], "minimum":0},
                            "contribution_caps_by_year": {"type":"object", "additionalProperties":{"type":"number", "minimum":0}},
                            "contribution_end_date": {"type":["string", "null"], "format":"date"},
                            "unrealized_gain_fraction": {"type":"number", "minimum":0, "maximum":1},
                            "interest_yield": {"type":"number", "minimum":0, "maximum":1},
                            "capital_gain_yield": {"type":"number", "minimum":0, "maximum":1},
                            "dividend_yield": {"type":"number", "minimum":0, "maximum":1},
                            "qualified_dividend_share": {"type":"number", "minimum":0, "maximum":1},
                            "reinvest_distributions": {"type":"boolean"},
                            "investment_income_profile": {"enum":["none", "stock_index", "balanced", "income", "cash"]},
                            "return_volatility": {"type":["number", "null"], "minimum":0}}},
        },
    }
