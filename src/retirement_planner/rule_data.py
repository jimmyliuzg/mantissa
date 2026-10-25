"""Read-only, packaged rule packs with stable content hashes."""
from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from importlib import resources
from typing import Any

DATA_VERSION = "1"
PACK_FIELDS = {"schema_version", "year", "tax", "tax_fields", "contributions"}
TAX_FIELDS = {
    "year", "name", "federal_brackets", "standard_deduction", "ltcg_brackets", "niit_thresholds",
    "niit_rate", "social_security_wage_base", "amt_exemption", "amt_phaseout_start", "amt_phaseout_rate",
    "amt_rate", "amt_26_limit", "irmaa_part_b", "irmaa_part_d", "irmaa_lookback_years", "fpl_base",
    "fpl_per_additional_person", "aca_tiers", "aca_fpl_cliff_ratio", "aca_silver_premiums",
    "estate_exemption_single", "estate_exemption_mfj", "estate_tax_rate", "salt_cap", "salt_phaseout_start",
    "salt_floor", "qcd_age", "charitable_deduction_floor_pct", "child_tax_credit",
    "child_tax_credit_phaseout_mfj", "child_tax_credit_phaseout_single", "ca_brackets",
    "ca_brackets_by_status", "ca_standard_deduction", "ca_itemized_phaseout_start", "itemized_reduction_rate",
    "inflation_factor", "citations", "status", "source", "source_status", "model_assumptions",
}
CONTRIBUTION_FIELDS = {
    "elec_deferral_limit", "catch_up_50_plus", "super_catch_up_60_63", "ira_limit",
    "ira_catch_up_50_plus", "hsa_individual", "hsa_family", "hsa_catch_up_55_plus",
    "roth_ira_income_limit_mfj", "ira_deduction_mfj_start", "ira_deduction_mfj_end",
    "ira_deduction_single_start", "ira_deduction_single_end", "ira_deduction_mfs_start",
    "ira_deduction_mfs_end", "ira_deduction_spousal_mfj_start", "ira_deduction_spousal_mfj_end",
    "roth_ira_mfj_start", "roth_ira_mfj_end", "roth_ira_single_start", "roth_ira_single_end",
    "roth_ira_mfs_start", "roth_ira_mfs_end",
}


@lru_cache(maxsize=None)
def _raw_pack_bytes(year: int) -> bytes:
    return resources.files("retirement_planner").joinpath("data", "rules", f"{year}.json").read_bytes()


def load_year_pack(year: int) -> dict[str, Any]:
    """Load a fresh copy of a published rules pack."""
    raw = _raw_pack_bytes(year)
    pack = json.loads(raw.decode("utf-8"))
    _validate_pack(pack, year)
    return pack


def _validate_pack(pack: Any, requested_year: int) -> None:
    path = f"rules/{requested_year}.json"
    if not isinstance(pack, dict):
        raise ValueError(f"{path}: expected an object")
    unknown = set(pack) - PACK_FIELDS
    if unknown:
        raise ValueError(f"{path}.{sorted(unknown)[0]}: unsupported pack field")
    if isinstance(pack.get("schema_version"), bool) or pack.get("schema_version") != 1:
        raise ValueError(f"{path}.schema_version: expected 1")
    if isinstance(pack.get("year"), bool) or pack.get("year") != requested_year:
        raise ValueError(f"{path}.year: must match the pack filename year")
    if "tax" in pack:
        tax = pack["tax"]
        if not isinstance(tax, dict):
            raise ValueError(f"{path}.tax: expected an object")
        unknown = set(tax) - TAX_FIELDS
        if unknown:
            raise ValueError(f"{path}.tax.{sorted(unknown)[0]}: unsupported tax field")
        required = TAX_FIELDS - {"source_status", "model_assumptions"}
        missing = required - set(tax)
        if missing:
            raise ValueError(f"{path}.tax.{sorted(missing)[0]}: required field is missing")
        if isinstance(tax.get("year"), bool) or tax.get("year") != requested_year:
            raise ValueError(f"{path}.tax.year: must match pack year")
        if tax.get("status") not in {"catalog_baseline", "published", "projected"}:
            raise ValueError(f"{path}.tax.status: unsupported tax status")
        for key in ("name", "source", "source_status"):
            if key in tax and (not isinstance(tax[key], str) or not tax[key].strip()):
                raise ValueError(f"{path}.tax.{key}: expected a non-empty string")
        for key in ("citations", "model_assumptions"):
            if key in tax and (not isinstance(tax[key], list) or any(not isinstance(item, str) for item in tax[key])):
                raise ValueError(f"{path}.tax.{key}: expected a list of strings")
        status_names = {"single", "mfj", "mfs", "hoh", "qss"}
        for key in ("federal_brackets", "ltcg_brackets", "niit_thresholds", "amt_exemption", "amt_phaseout_start", "standard_deduction", "ca_standard_deduction", "ca_itemized_phaseout_start"):
            mapping = tax[key]
            if not isinstance(mapping, dict) or set(mapping) != status_names:
                raise ValueError(f"{path}.tax.{key}: expected values for all five filing statuses")
            if key.endswith("brackets"):
                for status, rows in mapping.items():
                    _validate_brackets(rows, f"{path}.tax.{key}.{status}")
            else:
                for status, value in mapping.items():
                    _finite_number(value, f"{path}.tax.{key}.{status}", low=0, high=1_000_000_000_000)
        _validate_brackets(tax["ca_brackets"], f"{path}.tax.ca_brackets")
        by_status = tax["ca_brackets_by_status"]
        if not isinstance(by_status, dict) or set(by_status) != status_names:
            raise ValueError(f"{path}.tax.ca_brackets_by_status: expected values for all five filing statuses")
        for status, rows in by_status.items():
            _validate_brackets(rows, f"{path}.tax.ca_brackets_by_status.{status}")
        scalar_numbers = {
            "niit_rate": (0, 1), "social_security_wage_base": (0, 1_000_000_000_000),
            "amt_phaseout_rate": (0, 1), "amt_rate": (0, 1), "amt_26_limit": (0, 1_000_000_000_000),
            "irmaa_lookback_years": (0, 20), "fpl_base": (0, 1_000_000_000_000),
            "fpl_per_additional_person": (0, 1_000_000_000_000), "aca_fpl_cliff_ratio": (0, 100),
            "estate_exemption_single": (0, 1_000_000_000_000), "estate_exemption_mfj": (0, 1_000_000_000_000),
            "estate_tax_rate": (0, 1), "salt_floor": (0, 1_000_000_000_000), "qcd_age": (0, 150),
            "charitable_deduction_floor_pct": (0, 1), "child_tax_credit": (0, 1_000_000_000),
            "child_tax_credit_phaseout_mfj": (0, 1_000_000_000_000), "child_tax_credit_phaseout_single": (0, 1_000_000_000_000),
            "itemized_reduction_rate": (0, 1), "inflation_factor": (0, 100),
        }
        for key, (low, high) in scalar_numbers.items():
            _finite_number(tax[key], f"{path}.tax.{key}", low=low, high=high, integer=key == "irmaa_lookback_years")
        for key in ("salt_cap", "salt_phaseout_start"):
            if tax[key] is not None:
                _finite_number(tax[key], f"{path}.tax.{key}", low=0, high=1_000_000_000_000)
        for key in ("irmaa_part_b", "irmaa_part_d"):
            tiers = tax[key]
            if not isinstance(tiers, list) or not tiers:
                raise ValueError(f"{path}.tax.{key}: expected a non-empty tier list")
            previous_threshold = -1.0
            for index, tier in enumerate(tiers):
                loc = f"{path}.tax.{key}[{index}]"
                if not isinstance(tier, dict) or set(tier) != {"magi_threshold", "part_b_surcharge", "part_d_surcharge"}:
                    raise ValueError(f"{loc}: expected MAGI threshold and Part B/Part D surcharges")
                if tier["magi_threshold"] != "Infinity":
                    threshold = _finite_number(tier["magi_threshold"], f"{loc}.magi_threshold", low=0, high=1_000_000_000_000)
                    if threshold <= previous_threshold:
                        raise ValueError(f"{loc}.magi_threshold: values must increase")
                    previous_threshold = threshold
                elif index != len(tiers) - 1:
                    raise ValueError(f"{loc}.magi_threshold: Infinity is allowed only in the final tier")
                _finite_number(tier["part_b_surcharge"], f"{loc}.part_b_surcharge", low=0, high=1_000_000)
                _finite_number(tier["part_d_surcharge"], f"{loc}.part_d_surcharge", low=0, high=1_000_000)
        tiers = tax["aca_tiers"]
        if not isinstance(tiers, list) or not tiers:
            raise ValueError(f"{path}.tax.aca_tiers: expected a non-empty tier list")
        previous = -1.0
        for index, tier in enumerate(tiers):
            loc = f"{path}.tax.aca_tiers[{index}]"
            if not isinstance(tier, dict) or set(tier) != {"fpl_ratio", "applicable_pct"}:
                raise ValueError(f"{loc}: expected fpl_ratio and applicable_pct")
            ratio = _finite_number(tier["fpl_ratio"], f"{loc}.fpl_ratio", low=0, high=100)
            _finite_number(tier["applicable_pct"], f"{loc}.applicable_pct", low=0, high=1)
            if ratio <= previous:
                raise ValueError(f"{loc}.fpl_ratio: values must increase")
            previous = ratio
        premiums = tax["aca_silver_premiums"]
        if not isinstance(premiums, dict) or not premiums:
            raise ValueError(f"{path}.tax.aca_silver_premiums: expected a region map")
        for region, sizes in premiums.items():
            if not isinstance(sizes, dict) or not sizes:
                raise ValueError(f"{path}.tax.aca_silver_premiums.{region}: expected a family-size map")
            for size, amount in sizes.items():
                if size != "_default" and (not str(size).isdigit() or int(size) < 1):
                    raise ValueError(f"{path}.tax.aca_silver_premiums.{region}.{size}: unsupported family-size key")
                _finite_number(amount, f"{path}.tax.aca_silver_premiums.{region}.{size}", low=0, high=1_000_000)
        _validate_finite_tree(tax, f"{path}.tax")
    if "tax_fields" in pack:
        fields = pack["tax_fields"]
        if not isinstance(fields, dict):
            raise ValueError(f"{path}.tax_fields: expected an object")
        unknown = set(fields) - {"federal_bracket_rates"}
        if unknown:
            raise ValueError(f"{path}.tax_fields.{sorted(unknown)[0]}: unsupported published field")
        for key, metadata in fields.items():
            loc = f"{path}.tax_fields.{key}"
            if not isinstance(metadata, dict) or set(metadata) != {"value", "status", "source", "base_year"}:
                raise ValueError(f"{loc}: expected value, status, source, and base_year")
            if metadata["status"] != "published":
                raise ValueError(f"{loc}.status: expected published")
            if isinstance(metadata["base_year"], bool) or metadata["base_year"] != requested_year:
                raise ValueError(f"{loc}.base_year: must match pack year")
            if not isinstance(metadata["source"], str) or not metadata["source"].strip():
                raise ValueError(f"{loc}.source: expected a source citation")
            rates = metadata["value"]
            if key == "federal_bracket_rates":
                if not isinstance(rates, list) or len(rates) != 7:
                    raise ValueError(f"{loc}.value: expected seven marginal rates")
                for i, rate in enumerate(rates):
                    _finite_number(rate, f"{loc}.value[{i}]", low=0, high=1)
    if "contributions" in pack:
        contributions = pack["contributions"]
        if not isinstance(contributions, dict):
            raise ValueError(f"{path}.contributions: expected an object")
        for key, metadata in contributions.items():
            loc = f"{path}.contributions.{key}"
            if key not in CONTRIBUTION_FIELDS:
                raise ValueError(f"{loc}: unsupported contribution field")
            if not isinstance(metadata, dict) or set(metadata) != {"value", "status", "source", "base_year", "index"}:
                raise ValueError(f"{loc}: expected value, status, source, base_year, and index")
            _finite_number(metadata["value"], f"{loc}.value", low=0, high=10_000_000, integer=True)
            if metadata["status"] != "published":
                raise ValueError(f"{loc}.status: expected published")
            if isinstance(metadata["base_year"], bool) or metadata["base_year"] != requested_year:
                raise ValueError(f"{loc}.base_year: must match pack year")
            if not isinstance(metadata["source"], str) or not metadata["source"].strip():
                raise ValueError(f"{loc}.source: expected a source citation")
            if not isinstance(metadata["index"], bool):
                raise ValueError(f"{loc}.index: expected a boolean")


def _finite_number(value: Any, path: str, *, low: float, high: float, integer: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{path}: expected a finite number")
    if integer and not isinstance(value, int):
        raise ValueError(f"{path}: expected an integer")
    if not low <= value <= high:
        raise ValueError(f"{path}: expected a value in [{low}, {high}]")
    return float(value)


def _validate_brackets(rows: Any, path: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: expected a non-empty bracket list")
    previous = 0.0
    for index, row in enumerate(rows):
        loc = f"{path}[{index}]"
        if not isinstance(row, dict) or set(row) != {"upper", "rate"}:
            raise ValueError(f"{loc}: expected upper and rate")
        upper = row["upper"]
        if upper == "Infinity":
            if index != len(rows) - 1:
                raise ValueError(f"{loc}.upper: infinity is allowed only in the final bracket")
        else:
            upper = _finite_number(upper, f"{loc}.upper", low=0, high=1_000_000_000_000)
            if upper <= previous:
                raise ValueError(f"{loc}.upper: bracket bounds must increase")
            previous = upper
        _finite_number(row["rate"], f"{loc}.rate", low=0, high=1)


def _validate_finite_tree(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        _finite_number(value, path, low=-1_000_000_000_000, high=1_000_000_000_000)
        return
    if isinstance(value, str):
        if value == "Infinity":
            return
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_tree(child, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_tree(child, f"{path}.{key}")
        return
    raise ValueError(f"{path}: unsupported value type")


def available_pack_years(section: str | None = None) -> list[int]:
    return list(_cached_pack_years(section))


@lru_cache(maxsize=None)
def _cached_pack_years(section: str | None = None) -> tuple[int, ...]:
    root = resources.files("retirement_planner").joinpath("data", "rules")
    years = []
    for p in root.iterdir():
        if not p.name.endswith(".json"):
            continue
        year = int(p.name[:-5])
        if section is None or section in load_year_pack(year):
            years.append(year)
    return tuple(sorted(years))


@lru_cache(maxsize=None)
def pack_hash(year: int) -> str:
    raw = _raw_pack_bytes(year)
    return hashlib.sha256(raw).hexdigest()
