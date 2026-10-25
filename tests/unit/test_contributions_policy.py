from dataclasses import dataclass

import pytest

from retirement_planner.contributions import ContributionPolicy, validate_contribution_policy


@dataclass
class Limits:
    year: int = 2026
    ira_limit: int = 7_500
    ira_catch_up_50_plus: int = 1_100
    hsa_individual: int = 4_400
    hsa_family: int = 8_750
    hsa_catch_up_55_plus: int = 1_000
    ira_deduction_mfj_start: int = 129_000
    ira_deduction_mfj_end: int = 149_000
    ira_deduction_single_start: int = 81_000
    ira_deduction_single_end: int = 91_000
    ira_deduction_mfs_start: int = 0
    ira_deduction_mfs_end: int = 10_000
    ira_deduction_spousal_mfj_start: int = 242_000
    ira_deduction_spousal_mfj_end: int = 252_000
    roth_ira_mfj_start: int = 242_000
    roth_ira_mfj_end: int = 252_000
    roth_ira_single_start: int = 153_000
    roth_ira_single_end: int = 168_000
    roth_ira_mfs_start: int = 0
    roth_ira_mfs_end: int = 10_000


class Registry:
    def contributions_for_year(self, year, fallback_inflation):
        assert year == 2026
        return Limits()


def policy(owners, status="MFJ"):
    return ContributionPolicy({"owners": owners}, status, Registry())


def test_combined_traditional_and_roth_ira_cap_is_owner_specific():
    service = policy({"primary": {"ira_deduction": "deductible", "workplace_plan": False}})
    traditional = service.limit_for(
        "trad_ira", "primary", 2026, 40, magi_nominal=400_000,
        compensation_by_owner_nominal={"primary": 20_000},
    )
    roth = service.limit_for(
        "roth_ira", "primary", 2026, 40, magi_nominal=100_000,
        compensation_by_owner_nominal={"primary": 20_000},
        ira_contributed_by_owner_nominal={"primary": traditional.allowed_additional_nominal},
    )
    assert traditional.allowed_additional_nominal == 7_500
    assert traditional.deductible_additional_nominal == 7_500
    assert roth.allowed_additional_nominal == 0


def test_partial_roth_phaseout_uses_other_ira_pool_not_all_ira_contributions():
    service = policy({"primary": {"ira_deduction": "deductible", "workplace_plan": False}}, status="MFJ")
    roth = service.limit_for(
        "roth_ira", "primary", 2026, 40, magi_nominal=247_000,
        compensation_by_owner_nominal={"primary": 100_000},
        ira_contributed_by_owner_nominal={"primary": 5_000},
        ira_contributed_by_type_nominal={"traditional_ira": {"primary": 5_000}},
    )
    # The reduced Roth limit is $3,750, but the general $7,500 limit has only
    # $2,500 left after the traditional IRA contribution.
    assert roth.allowed_additional_nominal == 2_500


def test_roth_reduced_limit_uses_irs_ten_dollar_rounding_and_two_hundred_floor():
    service = policy({"primary": {}}, status="single")
    rounded = service.limit_for(
        "roth_ira", "primary", 2026, 40, magi_nominal=160_500,
        compensation_by_owner_nominal={"primary": 100_000},
        ira_contributed_by_owner_nominal={"primary": 0},
        ira_contributed_by_type_nominal={},
    )
    floor = service.limit_for(
        "roth_ira", "primary", 2026, 40, magi_nominal=167_990,
        compensation_by_owner_nominal={"primary": 100_000},
        ira_contributed_by_type_nominal={},
    )
    assert rounded.allowed_additional_nominal == 3_750
    assert floor.allowed_additional_nominal == 200

    limited_by_compensation = service.limit_for(
        "roth_ira", "primary", 2026, 40, magi_nominal=160_500,
        compensation_by_owner_nominal={"primary": 1_000},
        ira_contributed_by_type_nominal={},
    )
    assert limited_by_compensation.allowed_additional_nominal == 500


def test_spousal_ira_requires_explicit_eligibility_and_uses_shared_compensation():
    no_spousal = policy({"spouse": {"ira_deduction": "deductible", "workplace_plan": False}})
    denied = no_spousal.limit_for(
        "trad_ira", "spouse", 2026, 40, magi_nominal=80_000,
        compensation_by_owner_nominal={"primary": 30_000, "spouse": 0},
    )
    assert denied.allowed_additional_nominal == 0
    assert "spousal IRA eligibility" in denied.warnings[0]

    allowed = policy({
        "primary": {"ira_deduction": "deductible", "workplace_plan": True},
        "spouse": {"ira_deduction": "deductible", "workplace_plan": False, "spousal_ira_eligible": True},
    })
    result = allowed.limit_for(
        "trad_ira", "spouse", 2026, 50, magi_nominal=80_000,
        compensation_by_owner_nominal={"primary": 30_000, "spouse": 0},
    )
    assert result.allowed_additional_nominal == 8_600

    phaseout = allowed.limit_for(
        "trad_ira", "spouse", 2026, 40, magi_nominal=247_000,
        compensation_by_owner_nominal={"primary": 30_000, "spouse": 0},
    )
    assert phaseout.allowed_additional_nominal == pytest.approx(3_750)


def test_traditional_unknown_and_nondeductible_are_blocked_with_specific_warnings():
    unknown = policy({"primary": {}}).limit_for(
        "trad_ira", "primary", 2026, 40, magi_nominal=50_000,
        compensation_by_owner_nominal={"primary": 100_000},
    )
    nondeductible = policy({"primary": {"ira_deduction": "nondeductible"}}).limit_for(
        "trad_ira", "primary", 2026, 40, magi_nominal=50_000,
        compensation_by_owner_nominal={"primary": 100_000},
    )
    assert unknown.allowed_additional_nominal == 0
    assert "deductibility is unknown" in unknown.warnings[0]
    assert nondeductible.allowed_additional_nominal == 0
    assert "basis tracking" in nondeductible.warnings[0]


def test_covered_traditional_and_roth_limits_apply_phaseouts():
    service = policy({"primary": {"ira_deduction": "deductible", "workplace_plan": True}})
    deduction = service.limit_for(
        "trad_ira", "primary", 2026, 50, magi_nominal=139_000,
        compensation_by_owner_nominal={"primary": 50_000},
    )
    roth_service = policy({"primary": {}}, status="MFJ")
    roth = roth_service.limit_for(
        "roth_ira", "primary", 2026, 40, magi_nominal=247_000,
        compensation_by_owner_nominal={"primary": 50_000},
    )
    assert deduction.allowed_additional_nominal == pytest.approx(4_300)
    assert roth.allowed_additional_nominal == pytest.approx(3_750)
    blocked = roth_service.limit_for(
        "roth_ira", "primary", 2026, 40, compensation_by_owner_nominal={"primary": 50_000},
    )
    assert blocked.allowed_additional_nominal == 0
    assert "MAGI is unavailable" in blocked.warnings[0]


def test_family_hsa_pool_counts_employer_contributions_and_owner_catchups():
    service = policy({
        "primary": {"hsa_coverage": "family", "hsa_eligible": True, "hsa_eligible_months": 12},
        "spouse": {"hsa_coverage": "family", "hsa_eligible": True, "hsa_eligible_months": 12},
    })
    remaining = service.limit_for(
        "hsa", "primary", 2026, 56,
        hsa_contributed_by_owner_nominal={"spouse": 4_000},
        employer_hsa_contributions_nominal_by_owner={"primary": 1_000},
    )
    assert remaining.allowed_additional_nominal == 4_750
    assert remaining.maximum_nominal == 5_750

    fully_used = service.limit_for(
        "hsa", "spouse", 2026, 56,
        hsa_contributed_by_owner_nominal={"primary": 9_750},
    )
    assert fully_used.allowed_additional_nominal == 0


def test_hsa_month_proration_and_medicare_default_gate():
    partial = policy({"primary": {
        "hsa_coverage": "individual", "hsa_eligible": True, "hsa_eligible_months": 6,
    }}).limit_for("hsa", "primary", 2026, 55)
    assert partial.allowed_additional_nominal == 2_700

    medicare_default = policy({"primary": {
        "hsa_coverage": "individual", "hsa_eligible": True,
    }}).limit_for("hsa", "primary", 2026, 65)
    assert medicare_default.allowed_additional_nominal == 0
    assert "eligible months were not explicitly declared" in medicare_default.warnings[0]

    round_tripped = validate_contribution_policy({"owners": {"primary": {
        "hsa_coverage": "individual", "hsa_eligible": True,
    }}})
    still_blocked = ContributionPolicy(round_tripped, "MFJ", Registry()).limit_for("hsa", "primary", 2026, 65)
    assert still_blocked.allowed_additional_nominal == 0

    unknown_with_employer = policy({"primary": {
        "hsa_coverage": "individual", "hsa_employer_contribution_by_year": {"2026": 2_000},
    }}).limit_for("hsa", "primary", 2026, 45)
    assert unknown_with_employer.allowed_additional_nominal == 0
    assert unknown_with_employer.maximum_nominal == 0
    assert "not explicitly declared" in unknown_with_employer.warnings[0]


def test_family_hsa_counts_both_spouses_age_55_catchups():
    service = policy({
        "primary": {"hsa_coverage": "family", "hsa_eligible": True, "hsa_eligible_months": 12},
        "spouse": {"hsa_coverage": "family", "hsa_eligible": True, "hsa_eligible_months": 12},
    })
    result = service.limit_for(
        "hsa", "primary", 2026, 56,
        hsa_contributed_by_owner_nominal={"spouse": 9_750},
        ages_by_owner={"primary": 56, "spouse": 56},
    )
    assert result.allowed_additional_nominal == 1_000


def test_two_individual_hsas_have_separate_self_only_limits():
    service = policy({
        "primary": {"hsa_coverage": "individual", "hsa_eligible": True},
        "spouse": {"hsa_coverage": "individual", "hsa_eligible": True},
    })
    primary = service.limit_for("hsa", "primary", 2026, 40)
    spouse = service.limit_for(
        "hsa", "spouse", 2026, 40,
        hsa_contributed_by_owner_nominal={"primary": 4_400},
    )
    assert primary.allowed_additional_nominal == 4_400
    assert spouse.allowed_additional_nominal == 4_400


@pytest.mark.parametrize("first_owner,second_owner", [("primary", "spouse"), ("spouse", "primary")])
def test_mixed_family_and_individual_hsa_share_one_base_pool_in_either_order(first_owner, second_owner):
    service = policy({
        "primary": {"hsa_coverage": "individual", "hsa_eligible": True},
        "spouse": {"hsa_coverage": "family", "hsa_eligible": True},
    })
    first = service.limit_for("hsa", first_owner, 2026, 40)
    second = service.limit_for(
        "hsa", second_owner, 2026, 40,
        hsa_contributed_by_owner_nominal={first_owner: first.allowed_additional_nominal},
    )
    assert first.allowed_additional_nominal == 8_750
    assert second.allowed_additional_nominal == 0


def test_shared_workplace_cap_remains_owned_by_engine():
    service = policy({})
    assert service.limit_for("401k", "primary", 2026, 62) is None
    assert service.limit_for("brokerage", "primary", 2026, 62) is None


def test_policy_validation_has_field_specific_errors_and_year_normalization():
    normalized = validate_contribution_policy({"owners": {"primary": {
        "hsa_employer_contribution_by_year": {"2026": 1_000},
    }}})
    assert normalized["owners"]["primary"]["hsa_employer_contribution_by_year"] == {2026: 1_000.0}
    assert validate_contribution_policy(normalized) == normalized
    with pytest.raises(ValueError, match=r"contribution_policy\.owners\.primary\.hsa_eligible_months"):
        validate_contribution_policy({"owners": {"primary": {"hsa_eligible_months": 13}}})
    with pytest.raises(ValueError, match="not a supported field"):
        validate_contribution_policy({"owners": {"primary": {"unexpected": True}}})
    with pytest.raises(ValueError, match="non-negative number"):
        validate_contribution_policy({"owners": {"primary": {"hsa_employer_contribution_by_year": {"2026": float("nan")}}}})


def test_hsa_year_overrides_apply_eligibility_coverage_and_months():
    service = policy({"primary": {
        "hsa_coverage": "individual", "hsa_eligible": False,
        "hsa_eligible_by_year": {"2026": True},
        "hsa_coverage_by_year": {"2026": "family"},
        "hsa_eligible_months_by_year": {"2026": 6},
    }})
    result = service.limit_for("hsa", "primary", 2026, 55)
    assert result.allowed_additional_nominal == 4_875
