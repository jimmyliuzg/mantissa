# Rules catalog and forecast policies

Mantissa keeps published rule data in versioned JSON year packs under `src/retirement_planner/data/rules/`. `RuleRegistry` resolves tax law and contribution limits for one scenario. A registry owns its forecast policy and caches; packs are read from packaged resources and hashed for provenance.

## Pack maintenance

When adding an annual update, use an official source such as an IRS revenue procedure, notice, publication, or statute. Put only values established by that source in a pack and include the source citation, `base_year`, `status`, and indexing behavior for each contribution field. Keep the pack's `schema_version` at `1` unless the pack format changes, and set the root `year` to the filename year. `rule_data.py` validates pack keys, year labels, field types, ranges, and finite numeric values when loading.

A full `tax` section represents a complete catalog baseline. The 2024–2026 tax packs preserve the project's existing law data and are labeled `catalog_baseline` with `source_status: "mixed"`; some IRMAA and ACA inputs are illustrative model assumptions. They are useful for the model, but the label does not claim every parameter was independently verified as published tax law.

A pack can publish partial information without claiming the rest of that year's law is known. The 2028 pack records the permanent federal marginal-rate schedule established by Public Law 119-21, section 70101. The resolver uses those published rates with projected 2028 bracket thresholds based on the nearest full tax pack. `describe_year(2028)` reports `partial_published`, identifies the 2026 tax base, and marks `federal_bracket_rates` as published. The 2028 thresholds remain projections. Do not add an annual dollar limit as published until an official source has published that amount.

Projected amounts are model outputs, not official IRS forecasts.

Contribution entries are resolved field by field. The 2027 pack publishes only the HSA individual and family limits; all other limits still project from their latest available year. The 2028 HSA catch-up remains a fixed $1,000 entry, as provided by law, and has `index: false`. An indexed limit uses `index: true`; it grows from its `base_year` at the resolver's contribution growth rate until a later published field value takes over. Published values always take precedence over a projection for that field.

The pack's SHA-256 and per-field source/status/base year are available from `RuleRegistry.provenance()` and `RuleRegistry.describe_year(year)`. Forecasted values are marked `projected`; scenario overrides are marked `user`. Tax-pack provenance also carries the `catalog_baseline` or `mixed` caveat where it applies.

## Scenario forecasts

A scenario policy has this shape:

```json
{
  "schema_version": 1,
  "contribution_growth_rate": 0.03,
  "tax_threshold_growth_rate": 0.025,
  "changes": [
    {
      "id": "temporary-tax-change",
      "start_year": 2030,
      "end_year": 2034,
      "tax": {"federal_rate_multiplier": 1.05},
      "contributions": {"hsa_family": 12000}
    }
  ]
}
```

`start_year` and `end_year` are inclusive. A change lasting through 2034 is absent again in 2035, so the baseline law and contribution projections resume then. When multiple changes overlap, declaration order decides which later value wins for the same field. Dollar overrides are nominal in their start year; indexed tax dollar fields and indexed contribution fields grow at their applicable forecast rate in following years. Rates never index. Fixed fields such as the $1,000 HSA catch-up stay fixed. NIIT thresholds also stay fixed.

`tax_threshold_growth_rate` and `contribution_growth_rate` are optional. If omitted, callers can provide their economic inflation fallback to `law_for_year` and `contributions_for_year`. A scenario policy can change rates or thresholds for analysis; it does not edit a published pack.

The complete example at [`examples/policy_forecast.json`](../examples/policy_forecast.json) applies a fictional 5% multiplier to federal marginal rates from 2030 through 2034, forecasts contributions at 3%, and lets the tax scenario revert in 2035. The values in that change are hypothetical user assumptions, not official forecasts.

## Contribution-policy facts

`contribution_policy` is a separate, optional scenario section for owner-specific facts such as workplace-plan coverage, IRA deductibility, and HSA eligibility. It is not required during onboarding. When those facts are omitted, contribution planning follows the service's conservative defaults. It answers whether a contribution is eligible for the scenario; the rules catalog supplies the annual dollar limits.

## Verification

After changing packs or validation, run the focused catalog and contribution tests:

```sh
pytest -q tests/unit/test_rules.py tests/unit/test_tax_law.py tests/unit/test_sim_integration.py tests/unit/test_contributions_policy.py
```
