"""Policy forecast and packaged rules catalog contracts."""
import json

import pytest

from retirement_planner.rule_data import _validate_pack, available_pack_years, load_year_pack, pack_hash
from retirement_planner.rules import RuleRegistry, validate_policy
from retirement_planner.sim_integration import get_contribution_limits
from retirement_planner.tax_law import FilingStatus, TaxLawRegistry


def test_pack_data_roundtrips_and_has_versioned_provenance():
    assert available_pack_years() == [2024, 2025, 2026, 2027, 2028]
    assert available_pack_years("tax") == [2024, 2025, 2026]
    pack = load_year_pack(2025)
    assert json.loads(json.dumps(pack)) == pack
    assert len(pack_hash(2025)) == 64
    assert RuleRegistry().provenance()["packs"]["2025"]["status"] == "catalog_baseline"


def test_2028_partial_published_rates_do_not_publish_projected_thresholds():
    resolver = RuleRegistry({"schema_version": 1, "tax_threshold_growth_rate": 0.04})
    law = resolver.law_for_year(2028, policy_scenario="enacted")
    assert [b.rate for b in law.federal_brackets[FilingStatus.MFJ]] == [0.10, 0.12, 0.22, 0.24, 0.32, 0.35, 0.37]
    assert law.standard_deduction[FilingStatus.MFJ] == pytest.approx(32_200 * 1.04**2)
    description = resolver.describe_year(2028)
    assert description["tax"]["status"] == "partial_published"
    assert description["tax"]["base_year"] == 2026
    assert description["tax"]["fields"]["federal_bracket_rates"]["status"] == "published"
    assert description["contributions"]["fields"]["hsa_catch_up_55_plus"]["status"] == "published"
    assert description["contributions"]["values"]["hsa_catch_up_55_plus"] == 1_000
    assert resolver.provenance()["packs"]["2028"]["sections"]["tax_fields"]["federal_bracket_rates"] == "published"
    assert resolver.describe_year(2027)["contributions"]["status"] == "partial_published"


def test_cached_values_and_policy_are_returned_as_isolated_copies():
    pack = load_year_pack(2026)
    pack["contributions"]["hsa_individual"]["value"] = -1
    assert load_year_pack(2026)["contributions"]["hsa_individual"]["value"] == 4_400
    resolver = RuleRegistry({"schema_version": 1, "changes": []})
    exposed = resolver.policy
    exposed["changes"].append({"id": "bad", "start_year": 2030, "tax": {"niit_rate": 1}})
    law = resolver.law_for_year(2030)
    law.standard_deduction[FilingStatus.MFJ] = -1
    assert RuleRegistry().law_for_year(2030).standard_deduction[FilingStatus.MFJ] > 0


def test_published_year_pack_wins_over_forecast_growth():
    law = RuleRegistry({"schema_version": 1, "tax_threshold_growth_rate": 0.5}).law_for_year(2026)
    assert law.standard_deduction[FilingStatus.MFJ] == 32_200
    limits = RuleRegistry({"schema_version": 1, "contribution_growth_rate": 0.5}).contributions_for_year(2026)
    assert limits.hsa_individual == 4_400


def test_partial_2027_contribution_pack_only_overrides_published_hsa_fields():
    limits = get_contribution_limits(2027)
    assert limits.hsa_individual == 4_500
    assert limits.hsa_family == 9_000
    assert limits.ira_limit == int(7_500 * 1.025)
    described = RuleRegistry().describe_year(2027)
    assert described["tax"]["status"] == "projected"
    assert described["contributions"]["fields"]["hsa_individual"]["status"] == "published"
    assert described["contributions"]["fields"]["ira_limit"]["status"] == "projected"
    assert TaxLawRegistry().available_years() == [2024, 2025, 2026]


def test_scenario_overrides_are_isolated_and_revert_after_end_year():
    policy = {
        "schema_version": 1,
        "changes": [{
            "id": "temporary",
            "start_year": 2030,
            "end_year": 2031,
            "contributions": {"hsa_individual": 5_000},
            "tax": {"standard_deduction": {"mfj": 50_000}},
        }],
    }
    first = RuleRegistry(policy)
    second = RuleRegistry()
    assert first.contributions_for_year(2030).hsa_individual == 5_000
    assert first.contributions_for_year(2031).hsa_individual > 5_000
    assert first.contributions_for_year(2032).hsa_individual != first.contributions_for_year(2031).hsa_individual
    assert first.law_for_year(2030).standard_deduction[FilingStatus.MFJ] == 50_000
    assert first.law_for_year(2032).standard_deduction[FilingStatus.MFJ] != 50_000
    assert second.law_for_year(2030).standard_deduction[FilingStatus.MFJ] != 50_000
    assert first.describe_year(2030)["applied_change_ids"] == ["temporary"]
    assert first.describe_year(2030)["contributions"]["status"] == "user"
    assert first.describe_year(2030)["tax"]["status"] == "user"
    assert first.describe_year(2032)["applied_change_ids"] == []


def test_new_full_tax_pack_supersedes_older_partial_tax_fields(monkeypatch):
    import copy
    import retirement_planner.rules as rules_module

    years = {None: [2026, 2028, 2030], "tax": [2026, 2030], "tax_fields": [2028], "contributions": [2026]}
    monkeypatch.setattr(rules_module, "available_pack_years", lambda kind=None: years[kind])
    resolver = RuleRegistry()
    full_pack = copy.deepcopy(load_year_pack(2026))
    full_pack["year"] = 2030
    full_pack["tax"]["year"] = 2030
    full_pack["tax"]["name"] = "2030 test law"
    for brackets in full_pack["tax"]["federal_brackets"].values():
        brackets[0]["rate"] = 0.09
    resolver._pack_cache[2026] = load_year_pack(2026)
    resolver._pack_cache[2028] = {"year": 2028, "tax_fields": {"federal_bracket_rates": {
        "value": [0.15] * 7, "source": "test publication", "status": "published",
    }}}
    resolver._pack_cache[2030] = full_pack

    # The 2028 partial publication applies while 2026 remains the full base.
    assert resolver.law_for_year(2029).federal_brackets[FilingStatus.MFJ][0].rate == 0.15
    # Once a full 2030 law is selected, the older partial rates cannot overwrite it.
    assert resolver.law_for_year(2030).federal_brackets[FilingStatus.MFJ][0].rate == 0.09
    details = resolver.describe_year(2030)
    assert details["tax"]["base_year"] == 2030
    assert details["tax"]["fields"] == {}


def test_policy_changes_apply_in_declaration_order():
    policy = {"schema_version": 1, "changes": [
        {"id": "a", "start_year": 2030, "contributions": {"hsa_family": 10_000}},
        {"id": "b", "start_year": 2030, "contributions": {"hsa_family": 11_000}},
    ]}
    assert RuleRegistry(policy).contributions_for_year(2030).hsa_family == 11_000


def test_user_deduction_override_uses_fallback_inflation_and_merges_statuses():
    policy = {"schema_version": 1, "changes": [{"id": "sd", "start_year": 2030, "tax": {"standard_deduction": {"mfj": 50_000}}}]}
    law = RuleRegistry(policy).law_for_year(2031, fallback_inflation=0.03)
    assert law.standard_deduction[FilingStatus.MFJ] == pytest.approx(51_500)
    assert law.standard_deduction[FilingStatus.SINGLE] > 0


def test_tax_dollar_overrides_index_but_fixed_niit_threshold_does_not():
    policy = {"schema_version": 1, "tax_threshold_growth_rate": 0.03, "changes": [{
        "id": "tax-values", "start_year": 2030, "tax": {"salt_cap": 50_000, "niit_thresholds": {"mfj": 300_000}}
    }]}
    resolver = RuleRegistry(policy)
    assert resolver.law_for_year(2031).salt_cap == pytest.approx(51_500)
    assert resolver.law_for_year(2031).niit_thresholds[FilingStatus.MFJ] == 300_000


def test_effective_tax_rates_outside_unit_interval_are_rejected():
    policy = {"schema_version": 1, "changes": [{"id": "bad-rate", "start_year": 2030, "tax": {"federal_rate_addition": 0.8}}]}
    with pytest.raises(ValueError, match="effective federal rate"):
        RuleRegistry(policy).law_for_year(2030)


@pytest.mark.parametrize("policy, message", [
    ({"schema_version": 2}, "schema_version"),
    ({"schema_version": 1, "changes": [{"start_year": 2030, "contributions": {"hsa_family": float("nan")}}]}, "hsa_family"),
    ({"schema_version": 1, "changes": [{"start_year": 2030, "tax": {"niit_rate": 1.5}}]}, "niit_rate"),
])
def test_invalid_policy_fails_with_field_context(policy, message):
    with pytest.raises(ValueError, match=message):
        validate_policy(policy)


def test_policy_rejects_unknown_root_and_change_keys():
    with pytest.raises(ValueError, match="contribution_growt_rate"):
        validate_policy({"schema_version": 1, "contribution_growt_rate": 0.03})
    with pytest.raises(ValueError, match="startYear"):
        validate_policy({"schema_version": 1, "changes": [{"startYear": 2030}]})


@pytest.mark.parametrize("tax_override, message", [
    ({"social_security_wage_base": {}}, r"social_security_wage_base: expected a finite number"),
    ({"irmaa_lookback_years": []}, r"irmaa_lookback_years: expected an integer"),
    ({"aca_silver_premiums": 100}, r"aca_silver_premiums: expected a non-empty region-to-premiums mapping"),
    ({"irmaa_part_b": {}}, r"irmaa_part_b: expected a non-empty tier list"),
    ({"irmaa_part_d": [{"magi_threshold": "Infinity", "part_b_surcharge": 1, "part_d_surcharge": 2, "extra": 3}]}, r"irmaa_part_d\[0\]: expected exactly"),
    ({"aca_tiers": 0.2}, r"aca_tiers: expected a non-empty list"),
    ({"federal_brackets": [{"upper": 10_000, "rate": 0.1}]}, r"federal_brackets\[-1\].upper: final bracket must use 'Infinity'"),
    ({"federal_brackets": [{"upper": 10_000, "rate": 0.1, "note": "x"}, {"upper": "Infinity", "rate": 0.2}]}, r"federal_brackets\[0\]: expected exactly upper and rate"),
])
def test_tax_override_validation_rejects_wrong_shapes_and_incomplete_curves(tax_override, message):
    policy = {"schema_version": 1, "changes": [{"start_year": 2030, "tax": tax_override}]}
    with pytest.raises(ValueError, match=message):
        validate_policy(policy)


def test_tax_override_validation_accepts_complete_taxlaw_shapes():
    policy = {"schema_version": 1, "changes": [{"start_year": 2030, "tax": {
        "social_security_wage_base": 200_000,
        "irmaa_lookback_years": 2,
        "irmaa_part_b": [{"magi_threshold": 100_000, "part_b_surcharge": 0, "part_d_surcharge": 0},
                         {"magi_threshold": "Infinity", "part_b_surcharge": 100, "part_d_surcharge": 10}],
        "aca_silver_premiums": {"CA": {"1": 500, "2": 800}},
        "federal_brackets": [{"upper": 10_000, "rate": 0.1}, {"upper": "Infinity", "rate": 0.2}],
    }}]}
    assert validate_policy(policy)["changes"][0]["tax"] == policy["changes"][0]["tax"]


def test_partial_maps_merge_but_reject_invalid_bracket_curve_and_rate():
    good = {"schema_version": 1, "changes": [{"start_year": 2030, "tax": {"niit_thresholds": {"mfj": 300_000}}}]}
    law = RuleRegistry(good).law_for_year(2030)
    assert law.niit_thresholds[FilingStatus.MFJ] == 300_000
    assert law.niit_thresholds[FilingStatus.SINGLE] == 200_000
    bad = {"schema_version": 1, "changes": [{"start_year": 2030, "tax": {"federal_brackets": {"mfj": [{"upper": 50_000, "rate": 0.12}, {"upper": "Infinity", "rate": 1.1}]}}}]}
    with pytest.raises(ValueError, match=r"federal_brackets.mfj\[1\].rate"):
        validate_policy(bad)


def test_pack_validator_rejects_year_field_and_nonfinite_values():
    pack = load_year_pack(2027)
    pack["year"] = 2026
    with pytest.raises(ValueError, match="must match the pack filename"):
        _validate_pack(pack, 2027)
    pack = load_year_pack(2027)
    pack["contributions"]["hsa_family"]["value"] = float("inf")
    with pytest.raises(ValueError, match=r"hsa_family.value: expected a finite number"):
        _validate_pack(pack, 2027)


def test_legacy_tax_registry_stays_enacted_and_register_works():
    reg = TaxLawRegistry()
    assert reg.law_for_year(2024).year == 2024
    assert 2026 in reg.available_years()
