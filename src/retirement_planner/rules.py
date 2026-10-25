"""Versioned tax and contribution rules, with isolated user forecast policies."""
from __future__ import annotations

import copy
import math
from typing import Any

from .rule_data import DATA_VERSION, available_pack_years, load_year_pack, pack_hash

_RATE_KEYS = {"niit_rate", "amt_phaseout_rate", "amt_rate", "estate_tax_rate", "charitable_deduction_floor_pct", "itemized_reduction_rate", "tax_rate"}
_TAX_ALLOWED = {
    "federal_brackets", "standard_deduction", "ltcg_brackets", "niit_thresholds", "niit_rate",
    "social_security_wage_base", "amt_exemption", "amt_phaseout_start", "amt_phaseout_rate",
    "amt_rate", "amt_26_limit", "irmaa_part_b", "irmaa_part_d", "irmaa_lookback_years",
    "fpl_base", "fpl_per_additional_person", "aca_tiers", "aca_fpl_cliff_ratio",
    "aca_silver_premiums", "estate_exemption_single", "estate_exemption_mfj", "estate_tax_rate",
    "salt_cap", "salt_phaseout_start", "salt_floor", "qcd_age", "charitable_deduction_floor_pct",
    "child_tax_credit", "child_tax_credit_phaseout_mfj", "child_tax_credit_phaseout_single",
    "ca_brackets", "ca_brackets_by_status", "ca_standard_deduction", "ca_itemized_phaseout_start",
    "itemized_reduction_rate",
}
_POLICY_KEYS = {"schema_version", "contribution_growth_rate", "tax_threshold_growth_rate", "changes"}
_CHANGE_KEYS = {"id", "start_year", "end_year", "contributions", "tax"}


def validate_policy(policy: dict | None) -> dict:
    """Validate and return an isolated normalized policy mapping."""
    if policy is None:
        return {"schema_version": 1, "changes": []}
    if not isinstance(policy, dict):
        raise ValueError("policy: expected an object")
    if isinstance(policy.get("schema_version"), bool) or policy.get("schema_version") != 1:
        raise ValueError("policy.schema_version: expected 1")
    normalized = copy.deepcopy(policy)
    unknown = set(normalized) - _POLICY_KEYS
    if unknown:
        key = sorted(unknown)[0]
        raise ValueError(f"policy.{key}: unsupported policy field")
    normalized.setdefault("changes", [])
    for rate_key in ("contribution_growth_rate", "tax_threshold_growth_rate"):
        if rate_key in normalized:
            _number(normalized[rate_key], f"policy.{rate_key}", low=-0.5, high=1.0)
    changes = normalized.get("changes", [])
    if not isinstance(changes, list):
        raise ValueError("policy.changes: expected a list")
    seen_ids = set()
    for i, change in enumerate(changes):
        path = f"policy.changes[{i}]"
        if not isinstance(change, dict):
            raise ValueError(f"{path}: expected an object")
        unknown = set(change) - _CHANGE_KEYS
        if unknown:
            key = sorted(unknown)[0]
            raise ValueError(f"{path}.{key}: unsupported change field")
        start = _year(change.get("start_year"), f"{path}.start_year")
        end = _year(change["end_year"], f"{path}.end_year") if change.get("end_year") is not None else None
        if end is not None and end < start:
            raise ValueError(f"{path}.end_year: must be >= start_year")
        cid = change.get("id")
        if cid is not None:
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError(f"{path}.id: expected a non-empty string")
            if cid in seen_ids:
                raise ValueError(f"{path}.id: duplicate id {cid!r}")
            seen_ids.add(cid)
        for group in ("contributions", "tax"):
            values = change.get(group, {})
            if not isinstance(values, dict):
                raise ValueError(f"{path}.{group}: expected an object")
        contrib = change.get("contributions", {})
        known_contributions = {key for year in available_pack_years("contributions") for key in load_year_pack(year)["contributions"]}
        for key, value in contrib.items():
            if key not in known_contributions:
                raise ValueError(f"{path}.contributions.{key}: unsupported field")
            _number(value, f"{path}.contributions.{key}", low=0, high=10_000_000)
        tax = change.get("tax", {})
        for key, value in tax.items():
            if key in {"federal_rate_multiplier", "federal_rate_addition"}:
                _number(value, f"{path}.tax.{key}", low=-1 if key.endswith("addition") else 0, high=1 if key.endswith("addition") else 10)
            elif key in _TAX_ALLOWED:
                _validate_tax_override(key, value, f"{path}.tax.{key}")
            else:
                raise ValueError(f"{path}.tax.{key}: unsupported tax field")
    # Overlaps deliberately use declaration order; preserve that order in the normalized policy.
    return normalized


_STATUSES = {"single", "mfj", "mfs", "hoh", "qss"}
_STATUS_MAP_FIELDS = {
    "standard_deduction", "niit_thresholds", "amt_exemption", "amt_phaseout_start",
    "ca_standard_deduction", "ca_itemized_phaseout_start",
}
_BRACKET_FIELDS = {"federal_brackets", "ltcg_brackets", "ca_brackets", "ca_brackets_by_status"}
_DOLLAR_FIELDS = {
    "social_security_wage_base", "amt_26_limit", "fpl_base", "fpl_per_additional_person",
    "estate_exemption_single", "estate_exemption_mfj", "salt_cap", "salt_phaseout_start",
    "salt_floor", "child_tax_credit", "child_tax_credit_phaseout_mfj",
    "child_tax_credit_phaseout_single",
}


def _validate_tax_override(key: str, value: Any, path: str) -> None:
    """Check a policy override against the corresponding TaxLawVersion field shape."""
    if key in _BRACKET_FIELDS:
        _validate_bracket_tree(value, path)
        if isinstance(value, dict):
            for status in value:
                if status not in _STATUSES:
                    raise ValueError(f"{path}.{status}: unsupported filing status")
        return
    if key in _STATUS_MAP_FIELDS:
        if not isinstance(value, dict) or not value:
            raise ValueError(f"{path}: expected a non-empty filing-status mapping")
        for status, amount in value.items():
            if status not in _STATUSES:
                raise ValueError(f"{path}.{status}: unsupported filing status")
            _number(amount, f"{path}.{status}", low=0, high=1_000_000_000_000)
        return
    if key in {"irmaa_part_b", "irmaa_part_d"}:
        _validate_irmaa_tiers(value, path)
        return
    if key == "aca_tiers":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{path}: expected a non-empty list")
        previous_ratio = -1.0
        for i, tier in enumerate(value):
            loc = f"{path}[{i}]"
            if not isinstance(tier, dict) or set(tier) != {"fpl_ratio", "applicable_pct"}:
                raise ValueError(f"{loc}: expected exactly fpl_ratio and applicable_pct")
            ratio = _number(tier["fpl_ratio"], f"{loc}.fpl_ratio", low=0, high=100)
            _number(tier["applicable_pct"], f"{loc}.applicable_pct", low=0, high=1)
            if ratio <= previous_ratio:
                raise ValueError(f"{loc}.fpl_ratio: values must increase")
            previous_ratio = ratio
        return
    if key == "aca_silver_premiums":
        _validate_premium_map(value, path)
        return
    if key == "irmaa_lookback_years":
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10:
            raise ValueError(f"{path}: expected an integer in [0, 10]")
        return
    if key in {"salt_cap", "salt_phaseout_start"} and value is None:
        return
    if key in _RATE_KEYS:
        _number(value, path, low=0, high=1)
        return
    if key == "qcd_age":
        _number(value, path, low=0, high=150)
        return
    if key in _DOLLAR_FIELDS:
        _number(value, path, low=0, high=1_000_000_000_000)
        return
    if key == "aca_fpl_cliff_ratio":
        _number(value, path, low=0, high=100)
        return
    raise ValueError(f"{path}: unsupported tax field")


def _validate_premium_map(value: Any, path: str) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{path}: expected a non-empty region-to-premiums mapping")
    for region, premiums in value.items():
        loc = f"{path}.{region}"
        if not isinstance(region, str) or not region:
            raise ValueError(f"{loc}: expected a non-empty region name")
        if not isinstance(premiums, dict) or not premiums:
            raise ValueError(f"{loc}: expected a non-empty family-size mapping")
        for size, amount in premiums.items():
            if not isinstance(size, str) or not size.isdigit() or int(size) < 1:
                raise ValueError(f"{loc}.{size}: expected a positive family-size key")
            _number(amount, f"{loc}.{size}", low=0, high=1_000_000_000)


def _validate_irmaa_tiers(value: Any, path: str) -> None:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}: expected a non-empty tier list")
    previous = -1.0
    for i, tier in enumerate(value):
        loc = f"{path}[{i}]"
        expected = {"magi_threshold", "part_b_surcharge", "part_d_surcharge"}
        if not isinstance(tier, dict) or set(tier) != expected:
            raise ValueError(f"{loc}: expected exactly magi_threshold, part_b_surcharge, and part_d_surcharge")
        threshold = tier["magi_threshold"]
        if threshold == "Infinity":
            if i != len(value) - 1:
                raise ValueError(f"{loc}.magi_threshold: Infinity is allowed only in the final tier")
            current = math.inf
        else:
            current = _number(threshold, f"{loc}.magi_threshold", low=0, high=1_000_000_000_000)
        if current <= previous:
            raise ValueError(f"{loc}.magi_threshold: thresholds must increase")
        previous = current
        _number(tier["part_b_surcharge"], f"{loc}.part_b_surcharge", low=0, high=1_000_000)
        _number(tier["part_d_surcharge"], f"{loc}.part_d_surcharge", low=0, high=1_000_000)
    if value[-1]["magi_threshold"] != "Infinity":
        raise ValueError(f"{path}[-1].magi_threshold: final tier must use 'Infinity'")


def _validate_bracket_tree(value: Any, path: str) -> None:
    groups = value.items() if isinstance(value, dict) else [(None, value)]
    if isinstance(value, dict) and not value:
        raise ValueError(f"{path}: expected at least one filing-status bracket list")
    for status, brackets in groups:
        label = f"{path}.{status}" if status is not None else path
        if not isinstance(brackets, list):
            raise ValueError(f"{label}: expected a bracket list")
        if not brackets:
            raise ValueError(f"{label}: expected a non-empty bracket list")
        previous = 0.0
        for i, bracket in enumerate(brackets):
            loc = f"{label}[{i}]"
            if not isinstance(bracket, dict) or set(bracket) != {"upper", "rate"}:
                raise ValueError(f"{loc}: expected exactly upper and rate")
            upper = bracket["upper"]
            if upper != "Infinity":
                upper = _number(upper, f"{loc}.upper", low=0, high=1_000_000_000_000)
                if upper <= previous:
                    raise ValueError(f"{loc}.upper: bracket bounds must increase")
                previous = upper
            elif i != len(brackets) - 1:
                raise ValueError(f"{loc}.upper: Infinity is allowed only in the final bracket")
            _number(bracket["rate"], f"{loc}.rate", low=0, high=1)
        if brackets[-1]["upper"] != "Infinity":
            raise ValueError(f"{label}[-1].upper: final bracket must use 'Infinity'")


def _number(value: Any, path: str, *, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{path}: expected a finite number in [{low}, {high}]")
    return float(value)


def _year(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1900 or value > 3000:
        raise ValueError(f"{path}: expected year from 1900 to 3000")
    return value


def provenance(policy: dict | None = None) -> dict[str, Any]:
    normalized = validate_policy(policy)
    years = available_pack_years()
    return {"catalog_version": DATA_VERSION, "packs": {str(y): {"sha256": pack_hash(y), "status": "catalog_baseline" if "tax" in load_year_pack(y) else "partial_published", "sections": {"tax": load_year_pack(y).get("tax", {}).get("status") if "tax" in load_year_pack(y) else None, "tax_fields": {k: v["status"] for k, v in load_year_pack(y).get("tax_fields", {}).items()}, "contributions": "published" if "contributions" in load_year_pack(y) else None}, "contribution_fields": {k: v["status"] for k, v in load_year_pack(y).get("contributions", {}).items()}, "tax_source_status": load_year_pack(y).get("tax", {}).get("source_status")} for y in years}, "policy": normalized}


class RuleRegistry:
    """Per-scenario rule resolver. Instances keep no shared mutable forecast state."""
    def __init__(self, policy: dict | None = None):
        self._policy = validate_policy(policy)
        self._pack_cache: dict[int, dict[str, Any]] = {}
        self._law_cache: dict[tuple[int, str, float], Any] = {}
        self._contribution_cache: dict[tuple[int, float], Any] = {}

    @property
    def policy(self) -> dict:
        """Return an isolated copy; caller edits cannot alter this resolver."""
        return copy.deepcopy(self._policy)

    def _pack(self, year: int) -> dict[str, Any]:
        if year not in self._pack_cache:
            self._pack_cache[year] = load_year_pack(year)
        return self._pack_cache[year]

    def law_for_year(self, year: int, policy_scenario: str = "user", fallback_inflation: float = 0.025):
        from .tax_law import _inflate_law, _tax_from_pack
        if policy_scenario not in ("enacted", "user"):
            raise ValueError(f"Unsupported policy scenario: {policy_scenario}")
        cache_key = (year, policy_scenario, fallback_inflation)
        if cache_key in self._law_cache:
            return self._law_cache[cache_key]
        if policy_scenario == "enacted" and not self._policy["changes"]:
            pass
        tax_growth = self._policy.get("tax_threshold_growth_rate", fallback_inflation)
        tax_years = available_pack_years("tax")
        base_year = max((y for y in tax_years if y <= year), default=min(tax_years))
        base_pack = self._pack(base_year)
        base = _tax_from_pack(base_pack["tax"])
        if base_year == year:
            law = base
        else:
            factor = (1 + tax_growth) ** (year - base_year)
            law = _inflate_law(base, year, factor)
        published_tax_fields = {}
        for pack_year in available_pack_years("tax_fields"):
            # Partial publications supplement the selected full tax base only
            # until a newer complete annual tax pack supersedes them.
            if pack_year > year:
                break
            if pack_year <= base_year:
                continue
            published_tax_fields.update(self._pack(pack_year).get("tax_fields", {}))
        if published_tax_fields:
            law = self._apply_published_tax_fields(law, published_tax_fields)
        if policy_scenario == "user":
            law = self._apply_tax_changes(law, year, tax_growth)
        self._law_cache[cache_key] = law
        return law

    def _apply_published_tax_fields(self, law, published_fields):
        from dataclasses import replace
        from .tax_law import Bracket
        updates = {}
        rates = published_fields.get("federal_bracket_rates", {}).get("value")
        if rates is not None:
            updated = {}
            for status, brackets in law.federal_brackets.items():
                if len(brackets) != len(rates):
                    raise ValueError(f"published federal bracket rates do not match {status.value} bracket count")
                updated[status] = [Bracket(bracket.upper, rates[index]) for index, bracket in enumerate(brackets)]
            updates["federal_brackets"] = updated
        return replace(law, **updates) if updates else law

    def _apply_tax_changes(self, law, year, inflation):
        from dataclasses import replace
        from .tax_law import Bracket, FilingStatus
        updates = {}
        status_map = {s.value: s for s in FilingStatus}
        for change in self._policy["changes"]:
            if year < change["start_year"] or (change.get("end_year") is not None and year > change["end_year"]):
                continue
            tax = change.get("tax", {})
            # Rates are never indexed. A change expressed as a bracket multiplier
            # or addition is applied once to the selected baseline brackets.
            if "federal_rate_multiplier" in tax or "federal_rate_addition" in tax:
                mult = tax.get("federal_rate_multiplier", 1.0)
                add = tax.get("federal_rate_addition", 0.0)
                transformed = {
                    fs: [Bracket(b.upper, b.rate * mult + add) for b in row]
                    for fs, row in updates.get("federal_brackets", law.federal_brackets).items()
                }
                for fs, row in transformed.items():
                    for i, bracket in enumerate(row):
                        if not math.isfinite(bracket.rate) or not 0 <= bracket.rate <= 1:
                            raise ValueError(f"policy change {change.get('id', '<unnamed>')!r} yields effective federal rate outside [0, 1] for {fs.value} bracket {i}: {bracket.rate}")
                updates["federal_brackets"] = transformed
            index_factor = (1 + inflation) ** (year - change["start_year"])
            for key, value in tax.items():
                if key in ("federal_rate_multiplier", "federal_rate_addition"):
                    continue
                elif key in ("federal_brackets", "ltcg_brackets", "ca_brackets", "ca_brackets_by_status"):
                    if isinstance(value, dict):
                        current = updates.get(key, getattr(law, key)).copy()
                        current.update({status_map[s]: _decode_brackets(row, index_factor) for s, row in value.items()})
                        updates[key] = current
                    else:
                        updates[key] = _decode_brackets(value, index_factor)
                elif key in {"standard_deduction", "niit_thresholds", "amt_exemption", "amt_phaseout_start", "ca_standard_deduction", "ca_itemized_phaseout_start"}:
                    current = updates.get(key, getattr(law, key)).copy()
                    factor = 1.0 if key == "niit_thresholds" else index_factor
                    current.update({status_map[s]: v * factor for s,v in value.items()})
                    updates[key] = current
                elif key in {"irmaa_part_b", "irmaa_part_d"}:
                    from .tax_law import IrmaaTier
                    updates[key] = [IrmaaTier(**{**row, "magi_threshold": math.inf if row["magi_threshold"] == "Infinity" else row["magi_threshold"] * index_factor}) for row in value]
                elif key == "aca_tiers":
                    from .tax_law import AcaTier
                    updates[key] = [AcaTier(**row) for row in value]
                elif key == "aca_silver_premiums":
                    updates[key] = {region: {int(size) if str(size).isdigit() else size: amount * index_factor for size, amount in premiums.items()} for region, premiums in value.items()}
                elif key in _TAX_ALLOWED:
                    updates[key] = value if key in _NONINDEXED_TAX_FIELDS else value * index_factor if isinstance(value, (int, float)) else value
        return replace(law, **updates) if updates else law

    def _active_changes(self, year):
        return [c for c in self._policy["changes"] if c["start_year"] <= year and (c.get("end_year") is None or year <= c["end_year"])]

    def contributions_for_year(self, year: int, fallback_inflation: float = 0.025):
        from .sim_integration import ContributionLimits
        cache_key = (year, fallback_inflation)
        if cache_key in self._contribution_cache:
            return copy.deepcopy(self._contribution_cache[cache_key])
        contribution_years = available_pack_years("contributions")
        base_year = max((y for y in contribution_years if y <= year), default=min(contribution_years))
        growth = self._policy.get("contribution_growth_rate", fallback_inflation)
        values = {}
        provenance_fields = {}
        field_data_by_key = {}
        for pack_year in contribution_years:
            if pack_year > year:
                break
            for key, field_data in self._pack(pack_year)["contributions"].items():
                field_data_by_key[key] = (pack_year, field_data)
        for key, (field_year, field_data) in field_data_by_key.items():
            amount = field_data["value"]
            years = year - field_year
            if years and field_data["index"]:
                amount = int(amount * (1 + growth) ** years)
                status = "projected"
            else:
                status = "published" if years == 0 else "projected"
            provenance_fields[key] = {"status": status, "base_year": field_year, "source": field_data["source"]}
            values[key] = amount
        for change in self._active_changes(year):
            for key, value in change.get("contributions", {}).items():
                years_out = year - change["start_year"]
                # A nominal override is in force in its start year; IRS-indexed
                # fields then grow at the scenario contribution rate.
                pack_field = field_data_by_key.get(key, (0, {}))[1]
                index = pack_field.get("index", False)
                growth_factor = (1 + growth) ** years_out if index else 1.0
                values[key] = int(value * growth_factor)
                provenance_fields[key] = {"status": "user", "base_year": change["start_year"], "source": change.get("id", "user policy")}
        limits = ContributionLimits(year=year, **values)
        self._contribution_cache[cache_key] = limits
        return copy.deepcopy(limits)

    def describe_year(self, year: int, fallback_inflation: float = 0.025, policy_scenario: str = "user") -> dict[str, Any]:
        law = self.law_for_year(year, policy_scenario, fallback_inflation)
        contributions = self.contributions_for_year(year, fallback_inflation)
        tax_years = available_pack_years("tax")
        base_year = max((y for y in tax_years if y <= year), default=min(tax_years))
        active = self._active_changes(year) if policy_scenario == "user" else []
        active_tax_changes = [c for c in active if c.get("tax")]
        contribution_years = available_pack_years("contributions")
        contribution_metadata = {}
        for pack_year in contribution_years:
            if pack_year > year:
                break
            for key, field in self._pack(pack_year)["contributions"].items():
                contribution_metadata[key] = {"status": "published" if pack_year == year else "projected", "base_year": pack_year, "source": field["source"]}
        if policy_scenario == "user":
            for change in active:
                for key in change.get("contributions", {}):
                    contribution_metadata[key] = {"status": "user", "base_year": change["start_year"], "source": change.get("id", "user policy")}
        tax_field_metadata = {}
        for pack_year in available_pack_years("tax_fields"):
            if pack_year > year:
                break
            if pack_year <= base_year:
                continue
            for key, field in self._pack(pack_year).get("tax_fields", {}).items():
                tax_field_metadata[key] = {"status": "published", "base_year": pack_year, "source": field["source"]}
        tax_base_status = self._pack(year)["tax"].get("status", "catalog_baseline") if year in tax_years else "projected"
        if tax_field_metadata and tax_base_status == "projected":
            tax_base_status = "partial_published"
        tax_status = "user" if active_tax_changes else tax_base_status
        contribution_statuses = {metadata["status"] for metadata in contribution_metadata.values()}
        if "user" in contribution_statuses:
            contribution_status = "user"
        elif "published" in contribution_statuses and "projected" in contribution_statuses:
            contribution_status = "partial_published"
        elif "published" in contribution_statuses:
            contribution_status = "published"
        else:
            contribution_status = "projected"
        return {"year": year, "tax": {"status": tax_status, "base_status": tax_base_status, "source_status": self._pack(base_year)["tax"].get("source_status", "mixed"), "model_assumptions": copy.deepcopy(self._pack(base_year)["tax"].get("model_assumptions", [])), "base_year": base_year, "source": self._pack(base_year)["tax"].get("source"), "name": law.name, "fields": tax_field_metadata}, "contributions": {"status": contribution_status, "base_year": base_year, "values": contributions.__dict__.copy(), "fields": contribution_metadata}, "policy": policy_scenario, "applied_change_ids": [c.get("id", "user policy") for c in active]}

    def provenance(self, policy: dict | None = None) -> dict[str, Any]:
        return provenance(self._policy if policy is None else policy)


_NONINDEXED_TAX_FIELDS = {
    "niit_rate", "niit_thresholds", "amt_phaseout_rate", "amt_rate", "irmaa_lookback_years",
    "aca_tiers", "aca_fpl_cliff_ratio", "estate_tax_rate", "qcd_age",
    "child_tax_credit_phaseout_mfj", "child_tax_credit_phaseout_single", "itemized_reduction_rate",
    "charitable_deduction_floor_pct",
}


def _decode_brackets(value, factor=1.0):
    from .tax_law import Bracket
    def decode(rows):
        return [Bracket(float("inf") if x["upper"] == "Infinity" else float(x["upper"]) * factor, x["rate"]) for x in rows]
    return decode(value)
