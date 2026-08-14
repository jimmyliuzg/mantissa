"""Schema-aware validation for Mantissa JSON configurations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

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
    "age_events",
    "social_security", "glidepath", "withdrawal_strategy", "withdrawal_rate",
    "guardrail_floor_pct", "guardrail_ceiling_pct", "legacy_goal", "state",
    "family_size", "savings_order", "monetary_convention", "_comment",
}


def _issue(result, path, message, severity="error", code="invalid"):
    result.issues.append(ValidationIssue(path, message, severity, code))


def _number(result, value, path, low=None, high=None):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        _issue(result, path, "must be a number", code="type")
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
        if "balance" in account:
            _number(result, account["balance"], f"{path}.balance", 0)
        if "owner" in account and account["owner"] not in valid_owners:
            _issue(result, f"{path}.owner", "must be 'primary' or 'spouse'", code="reference")
        for field_name in ("growth_rate", "expense_ratio"):
            if field_name in account:
                _number(result, account[field_name], f"{path}.{field_name}", -1, 10)
        if "equity_pct" in account:
            _number(result, account["equity_pct"], f"{path}.equity_pct", 0, 1)

    for index, account_id in enumerate(config.get("savings_order", [])):
        if account_id not in ids:
            _issue(result, f"$.savings_order[{index}]", f"unknown account '{account_id}'", code="reference")

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
            "spouse": {"$ref": "#/$defs/person"},
            "accounts": {"type": "array", "items": {"$ref": "#/$defs/account"}},
            "monetary_convention": {"enum": ["real", "nominal"]},
        },
        "required": ["primary", "spouse"],
        "$defs": {
            "person": {"type": "object", "required": ["name", "birth_date", "retirement_date"]},
            "account": {"type": "object", "required": ["id", "name", "type", "balance"]},
        },
    }
