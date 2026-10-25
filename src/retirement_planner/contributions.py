"""Pure, owner-aware annual limits for IRA and HSA contributions.

The simulator stores cash flows in real dollars in some modes, while IRS
limits are nominal.  This service deliberately returns nominal legal limits;
the caller is responsible for translating a contribution amount to nominal
dollars before comparing it with these limits.

This is a policy gate, not a tax-return calculator.  It only allows a
traditional IRA contribution when the scenario explicitly says it is
deductible, and it does not model nondeductible IRA basis or Form 8606.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping, Optional


IRA_TYPES = {"trad_ira", "traditional_ira", "roth_ira"}
WORKPLACE_TYPES = {"401k", "trad_401k", "roth_401k", "403b", "tsp"}


@dataclass(frozen=True)
class PolicyDecision:
    """Annual policy result for one account and owner, in nominal dollars."""

    maximum_nominal: float
    allowed_additional_nominal: float
    deductible_additional_nominal: float = 0.0
    warnings: tuple[str, ...] = ()


def _number(obj: Any, name: str, default: float = 0.0) -> float:
    value = getattr(obj, name, default)
    return float(value if value is not None else default)


def _phaseout(base: float, magi: float, start: float, end: float) -> float:
    if magi <= start:
        return base
    if magi >= end or end <= start:
        return 0.0
    # IRS worksheets round to $10 increments. A continuous ceiling keeps the
    # service conservative without pretending to reproduce the full worksheet.
    return max(0.0, base * (end - magi) / (end - start))


def _rounded_reduced_limit(base: float, magi: float, start: float, end: float) -> float:
    """Apply the IRS reduced-limit worksheet's round-up and $200 floor."""
    if magi <= start:
        return base
    if magi >= end or end <= start:
        return 0.0
    reduction_fraction = min(1.0, max(0.0, (magi - start) / (end - start)))
    reduced = base * (1.0 - reduction_fraction)
    if reduced <= 0:
        return 0.0
    return max(200.0, math.ceil((reduced - 1e-9) / 10.0) * 10.0)


def _status(value: str) -> str:
    aliases = {
        "married_filing_jointly": "mfj", "married filing jointly": "mfj",
        "qualifying_surviving_spouse": "mfj", "qss": "mfj",
        "single": "single", "head_of_household": "single",
        "head of household": "single", "hoh": "single",
        "married_filing_separately": "mfs", "married filing separately": "mfs",
    }
    return aliases.get(str(value).strip().lower(), str(value).strip().lower())


def validate_contribution_policy(value: Any) -> dict[str, Any]:
    """Validate and normalize the optional scenario contribution policy.

    Errors include the exact policy path so config editors can point users to
    the field that needs correction. Unknown IRA deductibility remains an
    explicit conservative default.
    """
    if value is None:
        return {"owners": {}}
    if not isinstance(value, Mapping):
        raise ValueError("contribution_policy must be an object")
    normalized_input = value.get("_normalized_contribution_policy") is True
    unknown_root = set(value) - {"owners", "_normalized_contribution_policy"}
    if unknown_root:
        key = sorted(unknown_root)[0]
        raise ValueError(f"contribution_policy.{key} is not a supported field")
    raw_owners = value.get("owners", {})
    if not isinstance(raw_owners, Mapping):
        raise ValueError("contribution_policy.owners must be an object")
    normalized: dict[str, Any] = {"owners": {}}
    allowed_owner_fields = {
        "workplace_plan", "ira_deduction", "hsa_coverage", "hsa_eligible",
        "hsa_eligible_months", "hsa_employer_contribution_by_year",
        "spousal_ira_eligible", "hsa_eligible_by_year",
        "hsa_eligible_months_by_year", "hsa_coverage_by_year",
    }
    if normalized_input:
        allowed_owner_fields.add("_hsa_months_explicit")
    for owner, raw in raw_owners.items():
        path = f"contribution_policy.owners.{owner}"
        if owner not in {"primary", "spouse"}:
            raise ValueError(f"{path}: owner must be primary or spouse")
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path} must be an object")
        item = dict(raw)
        unknown = set(item) - allowed_owner_fields
        if unknown:
            key = sorted(unknown)[0]
            raise ValueError(f"{path}.{key} is not a supported field")
        workplace = item.get("workplace_plan")
        if workplace is not None and not isinstance(workplace, bool):
            raise ValueError(f"{path}.workplace_plan must be a boolean")
        deduction = item.get("ira_deduction", "unknown")
        if deduction not in {"deductible", "nondeductible", "unknown"}:
            raise ValueError(f"{path}.ira_deduction must be deductible, nondeductible, or unknown")
        coverage = item.get("hsa_coverage", "none")
        if coverage not in {"individual", "family", "none"}:
            raise ValueError(f"{path}.hsa_coverage must be individual, family, or none")
        eligible = item.get("hsa_eligible", False)
        if not isinstance(eligible, bool):
            raise ValueError(f"{path}.hsa_eligible must be a boolean")
        months = item.get("hsa_eligible_months", 12)
        if isinstance(months, bool) or not isinstance(months, int) or not 0 <= months <= 12:
            raise ValueError(f"{path}.hsa_eligible_months must be an integer from 0 through 12")
        spousal = item.get("spousal_ira_eligible", False)
        if not isinstance(spousal, bool):
            raise ValueError(f"{path}.spousal_ira_eligible must be a boolean")
        employer = item.get("hsa_employer_contribution_by_year", {})
        if not isinstance(employer, Mapping):
            raise ValueError(f"{path}.hsa_employer_contribution_by_year must be an object")
        normalized_employer: dict[int, float] = {}
        for raw_year, amount in employer.items():
            try:
                employer_year = int(raw_year)
            except (TypeError, ValueError):
                raise ValueError(f"{path}.hsa_employer_contribution_by_year keys must be calendar years") from None
            if str(employer_year) != str(raw_year) or employer_year < 1900 or employer_year > 9999:
                raise ValueError(f"{path}.hsa_employer_contribution_by_year keys must be calendar years")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
                raise ValueError(f"{path}.hsa_employer_contribution_by_year.{raw_year} must be a non-negative number")
            normalized_employer[employer_year] = float(amount)
        eligible_by_year = _validate_year_map(
            item.get("hsa_eligible_by_year", {}), path + ".hsa_eligible_by_year", bool
        )
        months_by_year = _validate_year_map(
            item.get("hsa_eligible_months_by_year", {}), path + ".hsa_eligible_months_by_year", int
        )
        if any(isinstance(months, bool) or not 0 <= months <= 12 for months in months_by_year.values()):
            raise ValueError(f"{path}.hsa_eligible_months_by_year values must be integers from 0 through 12")
        coverage_by_year = _validate_year_map(
            item.get("hsa_coverage_by_year", {}), path + ".hsa_coverage_by_year", str
        )
        if any(coverage not in {"individual", "family", "none"} for coverage in coverage_by_year.values()):
            raise ValueError(f"{path}.hsa_coverage_by_year values must be individual, family, or none")
        item["workplace_plan"] = workplace
        item["ira_deduction"] = deduction
        item["hsa_coverage"] = coverage
        item["hsa_eligible"] = eligible
        item["hsa_eligible_months"] = months
        item["_hsa_months_explicit"] = bool(
            raw.get("_hsa_months_explicit", "hsa_eligible_months" in raw)
        )
        item["spousal_ira_eligible"] = spousal
        item["hsa_employer_contribution_by_year"] = normalized_employer
        item["hsa_eligible_by_year"] = eligible_by_year
        item["hsa_eligible_months_by_year"] = months_by_year
        item["hsa_coverage_by_year"] = coverage_by_year
        normalized["owners"][owner] = item
    normalized["_normalized_contribution_policy"] = True
    return normalized


def _validate_year_map(value: Any, path: str, expected_type: type) -> dict[int, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    normalized: dict[int, Any] = {}
    for raw_year, item in value.items():
        try:
            year = int(raw_year)
        except (TypeError, ValueError):
            raise ValueError(f"{path} keys must be calendar years") from None
        if str(year) != str(raw_year) or year < 1900 or year > 9999:
            raise ValueError(f"{path} keys must be calendar years")
        if expected_type is bool:
            valid = isinstance(item, bool)
        elif expected_type is int:
            valid = isinstance(item, int) and not isinstance(item, bool)
        elif expected_type is str:
            valid = isinstance(item, str)
        else:
            valid = False
        if not valid:
            raise ValueError(f"{path}.{year} must be a {expected_type.__name__}")
        normalized[year] = item
    return normalized


class ContributionPolicy:
    """Resolve legal IRA/HSA ceilings from explicit household assumptions.

    ``policy`` accepts an ``owners`` mapping keyed by ``primary`` and
    ``spouse``. Missing IRA deduction/workplace-plan facts and missing HSA
    eligibility facts are treated conservatively. The policy object and every
    call input are read-only; callers pass current-year consumption explicitly,
    so previews and Monte Carlo paths do not share mutable contribution state.

    The limits provider must expose ``contributions_for_year(year,
    fallback_inflation)``. A provider may be omitted to use the legacy
    ``sim_integration.get_contribution_limits`` function.
    """

    def __init__(
        self,
        policy: Optional[Mapping[str, Any]] = None,
        filing_status: str = "MFJ",
        rule_registry: Any = None,
        fallback_inflation: float = 0.025,
    ) -> None:
        self.policy = validate_contribution_policy(policy)
        self.owners = dict(self.policy.get("owners") or {})
        self.filing_status = _status(filing_status)
        self.rule_registry = rule_registry
        self.fallback_inflation = fallback_inflation

    def _limits(self, year: int) -> Any:
        provider = self.rule_registry
        if provider is None:
            from .sim_integration import get_contribution_limits
            return get_contribution_limits(year, self.fallback_inflation)
        if hasattr(provider, "contributions_for_year"):
            return provider.contributions_for_year(year, self.fallback_inflation)
        if callable(provider):
            return provider(year, self.fallback_inflation)
        raise TypeError("limits_provider must provide contributions_for_year(year, fallback_inflation)")

    def _owner_policy(self, owner: str, year: Optional[int] = None) -> Mapping[str, Any]:
        raw = self.owners.get(owner, {}) or {}
        if year is None:
            return raw
        effective = dict(raw)
        if year in raw.get("hsa_eligible_by_year", {}):
            effective["hsa_eligible"] = raw["hsa_eligible_by_year"][year]
        if year in raw.get("hsa_eligible_months_by_year", {}):
            effective["hsa_eligible_months"] = raw["hsa_eligible_months_by_year"][year]
            effective["_hsa_months_explicit"] = True
        if year in raw.get("hsa_coverage_by_year", {}):
            effective["hsa_coverage"] = raw["hsa_coverage_by_year"][year]
        return effective

    @staticmethod
    def _cap_for_age(base: float, catch_up: float, age: int) -> float:
        return base + (catch_up if age >= 50 else 0.0)

    def _ira_deduction_ceiling(self, limits: Any, magi: Optional[float], owner: str, age: int) -> tuple[float, list[str]]:
        warnings: list[str] = []
        base = _number(limits, "ira_limit") + (
            _number(limits, "ira_catch_up_50_plus")
            if age >= 50 else 0.0
        )
        assumptions = self._owner_policy(owner)
        covered = assumptions.get("workplace_plan")
        if covered is None:
            warnings.append(f"{owner} traditional IRA funding is blocked because workplace-plan coverage is unknown.")
            return 0.0, warnings
        other = "spouse" if owner == "primary" else "primary"
        other_covered = self._owner_policy(other).get("workplace_plan") is True
        phaseout_applies = bool(covered) or (self.filing_status == "mfj" and not covered and other_covered)
        if not phaseout_applies:
            return base, warnings
        if magi is None:
            warnings.append(f"{owner} traditional IRA funding is blocked because annual MAGI is unavailable for the deduction phase-out.")
            return 0.0, warnings

        if self.filing_status == "mfj" and covered:
            start_name, end_name = "ira_deduction_mfj_start", "ira_deduction_mfj_end"
        elif self.filing_status == "mfj":
            start_name, end_name = "ira_deduction_spousal_mfj_start", "ira_deduction_spousal_mfj_end"
        elif self.filing_status == "mfs":
            start_name, end_name = "ira_deduction_mfs_start", "ira_deduction_mfs_end"
        else:
            start_name, end_name = "ira_deduction_single_start", "ira_deduction_single_end"
        start = getattr(limits, start_name, None)
        end = getattr(limits, end_name, None)

        # Married taxpayers filing jointly: the uncovered spouse has the
        # separate, higher phase-out when the other spouse is covered.
        if start is None or end is None:
            # Older rule packs did not hold phase-outs. Unknown means no
            # deductible funding can be safely authorized for a covered owner.
            warnings.append(f"{owner} traditional IRA funding is blocked because this year's deduction phase-out rule is unavailable.")
            return 0.0, warnings
        return _phaseout(base, magi, float(start), float(end)), warnings

    def _roth_ceiling(
        self,
        limits: Any,
        age: int,
        magi: Optional[float],
        compensation_limit: float,
        traditional_ira_used: float,
    ) -> tuple[float, list[str]]:
        annual_limit = self._cap_for_age(_number(limits, "ira_limit"), _number(limits, "ira_catch_up_50_plus"), age)
        base = min(annual_limit, compensation_limit)
        base_after_other_iras = max(0.0, base - traditional_ira_used)
        if magi is None:
            return 0.0, ["Roth IRA funding is blocked because annual MAGI is unavailable for the contribution phase-out."]
        if self.filing_status == "mfj":
            names = ("roth_ira_mfj_start", "roth_ira_mfj_end")
        elif self.filing_status == "mfs":
            names = ("roth_ira_mfs_start", "roth_ira_mfs_end")
        else:
            names = ("roth_ira_single_start", "roth_ira_single_end")
        start, end = (getattr(limits, n, None) for n in names)
        if start is None or end is None:
            return 0.0, ["Roth IRA funding is blocked because this year's MAGI phase-out rule is unavailable."]
        if magi <= float(start):
            reduced = base
        else:
            reduced = _rounded_reduced_limit(base, magi, float(start), float(end))
        # Worksheet 2-2 lines 9-11 subtracts contributions to other IRAs
        # (traditional IRAs) from the general limit before applying the Roth
        # reduced ceiling. Previously allocated Roth deposits are subtracted
        # by the caller from this separate Roth pool.
        return min(reduced, base_after_other_iras), []

    def _eligible_ira_compensation(
        self,
        owner: str,
        compensation_by_owner_nominal: Mapping[str, float],
        ira_contributed_by_owner_nominal: Mapping[str, float],
    ) -> tuple[float, list[str]]:
        owner_comp = max(0.0, float(compensation_by_owner_nominal.get(owner, 0.0) or 0.0))
        assumptions = self._owner_policy(owner)
        if self.filing_status == "mfj" and assumptions.get("spousal_ira_eligible") is True:
            total_comp = sum(max(0.0, float(v or 0.0)) for v in compensation_by_owner_nominal.values())
            other = "spouse" if owner == "primary" else "primary"
            unused_spousal_comp = max(
                0.0,
                total_comp - max(0.0, float(ira_contributed_by_owner_nominal.get(other, 0.0) or 0.0)),
            )
            return unused_spousal_comp, []
        if owner_comp > 0:
            return owner_comp, []
        return 0.0, [f"{owner} IRA funding is blocked because earned compensation or explicit spousal IRA eligibility is missing."]

    def _hsa_limit(
        self,
        limits: Any,
        owner: str,
        age: int,
        year: int,
        hsa_contributed_by_owner_nominal: Mapping[str, float],
        employer_hsa_contributions_nominal_by_owner: Optional[Mapping[str, float]],
        ages_by_owner: Optional[Mapping[str, int]],
    ) -> tuple[float, list[str]]:
        assumptions = self._owner_policy(owner, year)
        warnings: list[str] = []
        coverage = assumptions.get("hsa_coverage", "none")
        eligible = assumptions.get("hsa_eligible") is True
        if coverage not in {"individual", "family"} or not eligible:
            return 0.0, [f"{owner} HSA funding is blocked because eligible HDHP coverage is not explicitly declared."]
        if assumptions.get("_hsa_months_explicit"):
            months = max(0, min(12, int(assumptions["hsa_eligible_months"])))
        else:
            months = 12
            if age >= 65:
                return 0.0, [f"{owner} HSA funding is blocked at Medicare age because eligible months were not explicitly declared."]
        if months == 0:
            return 0.0, [f"{owner} HSA funding is blocked because declared eligible months are zero."]

        all_owners = set(self.owners) | set(hsa_contributed_by_owner_nominal)
        all_owners.add(owner)
        owner_policy_by_year = {hsa_owner: self._owner_policy(hsa_owner, year) for hsa_owner in all_owners}
        family_owners = {
            hsa_owner for hsa_owner, owner_policy in owner_policy_by_year.items()
            if owner_policy.get("hsa_eligible") is True
            and owner_policy.get("hsa_coverage") == "family"
            and int(owner_policy.get("hsa_eligible_months", 12)) > 0
        }
        family_pool = bool(family_owners)
        if family_pool:
            base_months = max(
                min(12, int(owner_policy_by_year[hsa_owner].get("hsa_eligible_months", 12)))
                for hsa_owner in family_owners
            )
            base = _number(limits, "hsa_family") * base_months / 12.0
            owner_months = months
            catch_up = _number(limits, "hsa_catch_up_55_plus") * min(12, owner_months) / 12.0 if age >= 55 else 0.0
        else:
            base = _number(limits, "hsa_individual") * months / 12.0
            catch_up = _number(limits, "hsa_catch_up_55_plus") * min(12, months) / 12.0 if age >= 55 else 0.0
        owner_cap = base + catch_up

        total_cap = base
        for hsa_owner in all_owners:
            hsa_owner_policy = owner_policy_by_year[hsa_owner]
            hsa_owner_age = age if hsa_owner == owner else int(
                (ages_by_owner or {}).get(hsa_owner, hsa_owner_policy.get("age", 0))
            )
            hsa_owner_months = int(hsa_owner_policy.get("hsa_eligible_months", 12))
            eligible_for_pool = hsa_owner_policy.get("hsa_eligible") is True and hsa_owner_months > 0
            if family_pool:
                eligible_for_pool = eligible_for_pool and hsa_owner_policy.get("hsa_coverage") in {"individual", "family"}
            else:
                eligible_for_pool = eligible_for_pool and hsa_owner == owner
            if eligible_for_pool and hsa_owner_age >= 55:
                total_cap += _number(limits, "hsa_catch_up_55_plus") * min(12, hsa_owner_months) / 12.0

        employer = dict(employer_hsa_contributions_nominal_by_owner or {})
        # Scenario-declared employer HSA deposits reduce the same limit. The
        # caller may pass these explicitly after gathering both owner records.
        for hsa_owner in all_owners:
            configured = self._owner_policy(hsa_owner).get("hsa_employer_contribution_by_year", {})
            employer.setdefault(hsa_owner, float(configured.get(year, configured.get(str(year), 0.0)) or 0.0))
        own_used = max(0.0, float(hsa_contributed_by_owner_nominal.get(owner, 0.0) or 0.0))
        own_used += max(0.0, float(employer.get(owner, 0.0) or 0.0))
        if family_pool:
            total_used = sum(max(0.0, float(v or 0.0)) for v in hsa_contributed_by_owner_nominal.values())
            total_used += sum(max(0.0, float(v or 0.0)) for v in employer.values())
        else:
            # Self-only coverage has a separate limit per spouse; one spouse's
            # deposits must not consume the other's individual HSA cap.
            total_used = own_used
        # Account owner's contributions can use the shared base pool, with
        # catch-up reserved for that account owner. Employer amounts consume
        # the same annual limit and are never treated as employee cash.
        return min(max(0.0, owner_cap - own_used), max(0.0, total_cap - total_used)), warnings

    def limit_for(
        self,
        account_type: str,
        owner: str,
        year: int,
        age: int,
        *,
        magi_nominal: Optional[float] = None,
        compensation_by_owner_nominal: Optional[Mapping[str, float]] = None,
        ira_contributed_by_owner_nominal: Optional[Mapping[str, float]] = None,
        ira_contributed_by_type_nominal: Optional[Mapping[str, Mapping[str, float]]] = None,
        hsa_contributed_by_owner_nominal: Optional[Mapping[str, float]] = None,
        employer_hsa_contributions_nominal_by_owner: Optional[Mapping[str, float]] = None,
        ages_by_owner: Optional[Mapping[str, int]] = None,
    ) -> Optional[PolicyDecision]:
        """Return this account's available annual contribution, in nominal dollars.

        The IRA consumption map must include all traditional and Roth IRA
        contributions already allocated for each owner. When supplied,
        ``ira_contributed_by_type_nominal`` maps ``traditional_ira`` and
        ``roth_ira`` to owner-specific contributions; this preserves the
        separate IRS worksheet caps while the total owner pool remains shared.
        Without that breakdown the service uses a conservative shared-consumed
        fallback. The HSA consumption
        map must include employee contributions; employer contributions are
        supplied separately and reduce the same household limit. Pass
        ``ages_by_owner`` to count each eligible spouse's age-55 HSA catch-up
        while calculating the other spouse's account ceiling.

        Workplace accounts return ``None`` so the engine's established shared
        401(k) deferral allocation continues to enforce their common cap.
        Unrestricted account types also return ``None``.
        """
        kind = account_type.lower()
        if kind in WORKPLACE_TYPES:
            return None
        limits = self._limits(year)
        warnings: list[str] = []
        if kind in IRA_TYPES:
            policy = self._owner_policy(owner)
            consumed = ira_contributed_by_owner_nominal or {}
            type_consumed = ira_contributed_by_type_nominal or {}
            traditional_used = sum(
                max(0.0, float(type_consumed.get(account_type, {}).get(owner, 0.0) or 0.0))
                for account_type in ("traditional_ira", "trad_ira", "traditional")
            )
            roth_used = sum(
                max(0.0, float(type_consumed.get(account_type, {}).get(owner, 0.0) or 0.0))
                for account_type in ("roth_ira", "roth")
            )
            if kind in {"trad_ira", "traditional_ira"}:
                mode = policy.get("ira_deduction", "unknown")
                if mode == "unknown":
                    return PolicyDecision(0.0, 0.0, warnings=(f"{owner} traditional IRA funding is blocked because deductibility is unknown.",))
                if mode == "nondeductible":
                    return PolicyDecision(0.0, 0.0, warnings=(f"{owner} nondeductible traditional IRA funding is blocked because IRA basis tracking is not modeled.",))
                if mode != "deductible":
                    return PolicyDecision(0.0, 0.0, warnings=(f"{owner} traditional IRA funding is blocked because ira_deduction must be deductible, nondeductible, or unknown.",))
                deduction_limit, deduction_warnings = self._ira_deduction_ceiling(limits, magi_nominal, owner, age)
                warnings.extend(deduction_warnings)
                account_cap = deduction_limit
            else:
                # Compensation is computed below, then used as the Roth
                # worksheet's line-6 base along with prior traditional IRA
                # contributions on line 9.
                account_cap = None
                roth_warnings = []
                warnings.extend(roth_warnings)

            comp_map = compensation_by_owner_nominal or {}
            compensation_cap, comp_warnings = self._eligible_ira_compensation(owner, comp_map, consumed)
            warnings.extend(comp_warnings)
            annual_limit = self._cap_for_age(_number(limits, "ira_limit"), _number(limits, "ira_catch_up_50_plus"), age)
            owner_limit = min(annual_limit, compensation_cap)
            if kind == "roth_ira":
                account_cap, roth_warnings = self._roth_ceiling(
                    limits, age, magi_nominal, compensation_cap, traditional_used
                )
                warnings.extend(roth_warnings)
            household_compensation = sum(max(0.0, float(v or 0.0)) for v in comp_map.values())
            household_used = sum(max(0.0, float(v or 0.0)) for v in consumed.values())
            owner_used = max(0.0, float(consumed.get(owner, 0.0) or 0.0))
            if ira_contributed_by_type_nominal is None:
                # Existing direct callers without a type breakdown retain a
                # conservative aggregate subtraction.
                account_used = owner_used
            else:
                account_used = traditional_used if kind in {"trad_ira", "traditional_ira"} else roth_used
            additional = min(
                max(0.0, owner_limit - owner_used),
                max(0.0, account_cap - account_used),
                max(0.0, household_compensation - household_used),
            )
            return PolicyDecision(owner_limit, additional, additional if kind in {"trad_ira", "traditional_ira"} else 0.0, tuple(warnings))

        if kind == "hsa":
            max_additional, hsa_warnings = self._hsa_limit(
                limits, owner, age, year,
                hsa_contributed_by_owner_nominal or {},
                employer_hsa_contributions_nominal_by_owner,
                ages_by_owner,
            )
            used = max(0.0, float((hsa_contributed_by_owner_nominal or {}).get(owner, 0.0) or 0.0))
            employer = max(0.0, float((employer_hsa_contributions_nominal_by_owner or {}).get(owner, 0.0) or 0.0))
            # A configured employer deposit is not authority to fund the HSA
            # or count it toward an allowed contribution when eligibility is
            # unknown. The engine separately credits verified employer assets.
            maximum = 0.0 if hsa_warnings else used + employer + max_additional
            return PolicyDecision(maximum, max_additional, 0.0, tuple(hsa_warnings))
        return None
