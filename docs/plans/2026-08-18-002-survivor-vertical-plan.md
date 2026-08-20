---
title: "Deterministic Survivor Vertical - Plan"
date: 2026-08-18
type: implementation-plan
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Deterministic Survivor Vertical - Plan

## Goal Capsule

- **Objective:** Make deterministic retirement projections reflect one spouse's configured death and its tax, income, spending, healthcare, account, and estate consequences.
- **Authority:** Approved survivor Product Contract from the 2026-08-18 brainstorm; existing model behavior remains baseline where this plan does not explicitly change it.
- **Stop condition:** Golden fixtures prove both death orders and second-death estate timing; deterministic and longevity-derived Monte Carlo paths use the same transition rules; existing release gates remain green.
- **Execution profile:** One transition model, implemented in dependency order, with proof-first golden tests before production changes where practical.
- **Tail ownership:** Stochastic mortality, full inherited-account rules, claiming-law corrections, and annual/monthly event unification remain follow-on work.

## Product Contract

### Summary

Mantissa already contains household-state and survivor-transition helpers, but the main deterministic and Monte Carlo flows hardcode both spouses alive, calculate Social Security independently, keep household coverage assumptions static, and use an incorrect estate trigger. This slice connects configured longevity ages to one auditable annual survivor transition.

### Problem Frame

A retirement plan can materially change when one spouse dies: filing status narrows, Social Security changes, ACA family size changes, expenses fall, pretax-account ownership changes, and the estate is ultimately taxed at the second death. These effects must appear in projection rows and totals rather than existing only in disconnected helper classes.

### Requirements

- R1. The projection derives deterministic death years from each person's birth year and configured longevity age without sampling mortality.
- R2. A configured death year is treated as the person's final full modeled year: death-year income tax remains MFJ, and survivor transitions apply beginning in the following year.
- R3. After first death, filing status follows existing tax rules: QSS for two years when dependents qualify, then HOH when dependents remain or Single otherwise.
- R4. After first death, Social Security uses only benefits payable under the existing claiming schedule: death-year income retains both payable benefits, and later survivor income is the higher of the survivor's payable benefit and the deceased person's payable benefit at death; no future benefit is created for an unclaimed deceased spouse.
- R5. Post-death ACA family size equals surviving adults plus active dependents; Medicare covered-adult count equals living adults at Medicare age. These counts feed their respective coverage calculations.
- R6. Post-death expenses equal the configured survivor expense ratio, defaulting to 75% of all active expenses. The ratio is explicit and validated; this is an acknowledged approximation.
- R7. At first death, eligible pretax accounts transfer through a spousal-rollover approximation; isolated RMD tests prove future calculations use survivor ownership and age. Deterministic/Monte Carlo numeric RMD parity is out of scope.
- R8. Estate tax is assessed once at the second configured death year, after that year's projection, using the surviving/single estate convention; first-death spousal transfer does not trigger estate tax in this slice. Equal death years use one combined/MFJ estate event. Estate tax is reported separately and reduces net cash flow through additive post-estate net-worth fields.
- R9. Deterministic projection and Monte Carlo use the same longevity-derived survivor transition rules and expose auditable state fields. Parity covers survivor state and estate behavior, not deterministic numeric RMDs.
- R10. Existing non-Social-Security income stream date behavior, current Social Security claiming calculation, and annual event granularity remain unchanged.

### Acceptance Examples

- **AE1 — Primary dies first:** Given primary death year before spouse death year, the death year is MFJ with both modeled benefits; the next year has survivor filing status, one fewer adult for coverage, reduced expenses, survivor Social Security, and rolled-over pretax ownership.
- **AE2 — Spouse dies first:** The same transitions work with reversed account ownership and survivor identity; no primary-specific assumption leaks into the result.
- **AE3 — Dependents:** Any active dependent is used as the first-slice approximation for QSS/HOH qualification; QSS applies for two post-death years, then status becomes HOH. Without active dependents, post-death status is Single. ACA activity continues to use existing age-based rules.
- **AE4 — Second death:** Estate tax is zero at first death, appears once in a separate `estate_tax` field at the second configured death year, reduces final net cash flow, populates `estate_value_before_tax` and `net_worth_after_estate`, appears in `total_estate_tax`, and no projection years continue after settlement. Equal death years use the combined/MFJ estate convention.
- **AE5 — Monte Carlo parity:** With existing longevity ages and equivalent return inputs, Monte Carlo and deterministic paths match alive state, filing status, ACA/Medicare counts, survivor income, expense scaling, and estate timing. RMD ownership is tested separately.

### Success Criteria

- Golden fixtures cover both death orders, death-year semantics, approximate dependent/QSS status, claimed-benefit-only survivor Social Security, all-expense ratio, separate ACA/Medicare counts, RMD ownership, and second-death estate tax.
- Projection rows expose enough state to explain each transition: alive flags, filing status, household size, survivor identity, and estate tax.
- No global random calls are introduced for deterministic survivor behavior.
- The default release gate and optional-feature gates remain green.

### Scope Boundaries

**In scope:** deterministic longevity-derived death years, annual survivor state, filing status, claimed-benefit-only survivor Social Security, separate ACA/Medicare household counts, configurable all-expense survivor scaling, spousal rollover approximation, isolated RMD ownership tests, second-death estate tax, narrowed deterministic/MC parity fixtures, and report-visible transition fields.

**Deferred for later:** stochastic mortality and explicit RNG plumbing, inherited-account 10-year rules, beneficiary classifications, remarriage and dependent Social Security benefits, Social Security claiming-law corrections, estate portability, monthly/partial-year death timing, and annual/monthly event-loop unification.

**Outside this product slice:** investment, tax, legal, or fiduciary recommendations.

## Planning Contract

### Key Technical Decisions

- **KTD1 — One deterministic transition source:** Derive annual household state from existing longevity ages in one shared pure transition helper consumed by deterministic and Monte Carlo paths. Do not make the existing `HouseholdState.advance_year()` global-random path authoritative for this slice; no new configured-death API is required.
- **KTD2 — Full-year death semantics:** Treat death year as a final full year for income tax, payable Social Security, expenses, and MFJ status. Apply survivor state beginning the next year; assess second-death estate tax at the end of the second death year.
- **KTD3 — Explicit all-expense ratio:** Add a scenario/config setting with default `0.75`, validate it in the config layer, and apply it to the full active expense total after first death, including existing debt, medical, coverage, and one-time expense categories. Preserve existing inflation/stress ordering unless a focused fixture proves otherwise.
- **KTD4 — Claimed-benefit-only Social Security:** Retain both payable benefits in the death year; after death, select the higher payable benefit observed at death and continue it with existing COLA behavior. Do not create a future benefit for an unclaimed deceased spouse or repair claiming-age law here.
- **KTD5 — Separate coverage counts:** Derive ACA family size from living adults plus active dependents, and Medicare covered-adult count from living adults at Medicare age. Do not use one count for both programs.
- **KTD6 — Spousal rollover approximation:** Reassign eligible pretax balances in local simulation state at first death for future RMD age/ownership calculations. Test this independently; do not require deterministic numeric RMD parity or model inherited-account rules.
- **KTD7 — Separate estate reporting:** Suppress first-death estate tax; assess once at second death using the single/survivor convention, or combined/MFJ for equal death years; expose `estate_tax`, `total_estate_tax`, `estate_value_before_tax`, and `net_worth_after_estate`; subtract the amount from final net cash flow without redefining ordinary `taxes` or existing `net_worth`.
- **KTD8 — Tax-status normalization:** Normalize the string status from `sim_integration.py` to the `FilingStatus` enum before every tax call, including housing-event tax, so both deterministic and Monte Carlo paths use the same brackets and deductions.
- **KTD9 — State visibility over hidden mutation:** Add stable projection fields for alive state, survivor, filing status, ACA/Medicare counts, expense ratio, and estate tax. Preserve existing output fields for compatibility.
- **KTD10 — Preserve non-SS income:** Keep existing income-stream date behavior unchanged; do not add owner-death termination or continuation policy in this slice.

### High-Level Technical Design

The annual loop will compute a `HouseholdState`-compatible snapshot before tax and cash-flow decisions. The snapshot contains both alive flags, survivor identity, filing status, ACA family size, Medicare covered-adult count, and death-year transition metadata. Cash flow, Social Security, coverage, and estate calculations consume that snapshot. The same longevity-derived snapshot rules are used by deterministic projection and Monte Carlo; no stochastic mortality or new death-year API is introduced.

At first death, account ownership is updated in local simulation state through a spousal-rollover approximation, with RMD ownership/calculation tested independently because deterministic projection does not model numeric withdrawals. At second death, the final estate value is assessed and recorded in separate estate-tax fields; estate tax reduces final net cash flow and populates additive post-estate net-worth fields while existing `net_worth` remains pre-estate. Death-year semantics are deliberately annual rather than partial-year; partial-year timing remains deferred.

### Existing Patterns to Follow

- `src/retirement_planner/household.py:185` for survivor-transition vocabulary and filing-status phases.
- `src/retirement_planner/tax_law.py:859` for filing-status rules and existing `FilingStatus` values.
- `src/retirement_planner/engine.py:2315` for the deterministic annual loop, MAGI history, balances, and tax totals.
- `src/retirement_planner/engine.py:1982` for current Social Security calculation behavior.
- `src/retirement_planner/simulators.py:69`, `src/retirement_planner/engine.py:1831`, and `src/retirement_planner/sim_integration.py:19` for Monte Carlo integration, tax-status adapters, and parity tests.
- `tests/unit/test_household.py` and `tests/regression/test_mc_deterministic_parity.py` for existing household and parity coverage.

### Assumptions

- Longevity ages are the configured deterministic death-year source; no mortality draw occurs.
- Any active dependent is the documented approximation for QSS/HOH qualification; no new dependent qualification field is added.
- Survivor expense ratio applies to the full active expense total, including existing categories, as an explicit approximation.
- Existing Social Security annual benefit calculation determines which benefits are payable at death and supplies survivor selection.
- Eligible pretax account types are those already recognized by the engine's RMD path; ownership changes remain local to each simulation state.
- Existing `net_worth` remains pre-estate for compatibility; additive post-estate fields carry settlement effects.

### Sequencing

1. Characterize current helper, tax-status adapter, annual-loop, and output behavior with failing/golden fixtures.
2. Add deterministic household transition and projection-state fields, including both death orders.
3. Consolidate filing-status delivery into tax calls; integrate claimed-benefit-only Social Security, separate ACA/Medicare counts, and all-expense scaling.
4. Integrate local spousal rollover state, isolated RMD ownership tests, second-death estate timing, separate estate totals, and termination.
5. Route Monte Carlo through the same longevity-derived transition logic and add narrowed parity fixtures.
6. Run release gates, inspect reports/CLI output, and review scope.

## Implementation Units

### U1. Deterministic household transition contract

- **Goal:** Produce one annual survivor snapshot from configured death years.
- **Requirements:** R1, R2, R3, R9.
- **Files:** `src/retirement_planner/household.py`, `src/retirement_planner/engine.py`, `src/retirement_planner/sim_integration.py`, `src/retirement_planner/config/validation.py`, `tests/unit/test_household.py`, `tests/regression/test_survivor_vertical.py`.
- **Approach:** Extend the existing household vocabulary with deterministic transition evaluation and explicit death-year semantics. Consolidate filing-status input and normalize it to `FilingStatus` before every tax call, including housing-event tax. Use existing active-dependent count as the documented QSS/HOH approximation. Keep the transition pure and free of global randomness.
- **Test scenarios:** Both alive; primary final year; spouse final year; first post-death year; QSS years 1–2 with an active dependent; post-QSS HOH; no-dependent Single; same-year deaths use combined/MFJ estate marker; second-death termination marker; filing-status adapter accepts either deceased spouse and normalizes enum input.
- **Verification:** Focused household and new survivor regression tests before downstream integration.

### U2. Survivor filing, benefits, household size, and spending

- **Goal:** Apply the transition snapshot to annual income, taxes, ACA/coverage inputs, and expenses.
- **Requirements:** R3, R4, R5, R6, R9, R10.
- **Files:** `src/retirement_planner/models.py`, `src/retirement_planner/engine.py`, `src/retirement_planner/config/validation.py`, `tests/regression/test_survivor_vertical.py`, `tests/integration/test_engine_tax.py`, `tests/unit/test_tax_law.py`.
- **Approach:** Add and validate the survivor expense ratio with default 0.75; derive separate ACA family size and Medicare covered-adult count; use the existing tax filing-status vocabulary; preserve payable death-year benefits and select the higher payable benefit observed at death thereafter. Keep non-Social-Security income stream date behavior unchanged. Add stable row fields for alive state, survivor, filing status, coverage counts, expense ratio, and transition effects.
- **Test scenarios:** Primary-first and spouse-first benefit selection; unclaimed deceased benefit does not appear; death-year MFJ; post-death Single; QSS/HOH approximation with active dependents; ACA family size and Medicare adult count changes; 75% default and custom all-expense ratio; tax calculation receives post-death filing status; owner income streams retain existing date behavior.
- **Verification:** Focused regression/integration tests and representative CLI JSON projection inspection.

### U3. Spousal rollover, RMD ownership, and estate timing

- **Goal:** Make account ownership and estate tax follow survivor state.
- **Requirements:** R7, R8, R9.
- **Files:** `src/retirement_planner/engine.py`, `src/retirement_planner/household.py`, `tests/regression/test_survivor_vertical.py`, `tests/regression/test_audit_regressions.py`, `tests/integration/test_engine_tax.py`.
- **Approach:** Reassign eligible pretax account state locally to the survivor at first death for subsequent RMD ownership/calculation tests; never mutate shared `Account` objects across Monte Carlo runs. Suppress first-death estate tax, assess second-death estate tax once using surviving/single convention or combined/MFJ for equal death years, expose separate row/result estate-tax fields, subtract it from final net cash flow, populate additive post-estate net-worth fields, and stop after settlement.
- **Test scenarios:** Primary-owned pretax account rolls to surviving spouse; spouse-owned account rolls to primary; survivor age drives isolated later RMD calculation; first-death estate tax is zero; second-death `estate_tax` appears exactly once; `total_estate_tax` is populated; `estate_value_before_tax` and `net_worth_after_estate` are populated; ordinary `taxes` and existing `net_worth` remain distinct; final net cash flow reflects estate tax; equal death years use combined/MFJ; no post-settlement rows.
- **Verification:** Golden balance/RMD/estate fixtures plus existing audit regression suite.

### U4. Monte Carlo parity and report contracts

- **Goal:** Reuse deterministic survivor rules in longevity-derived Monte Carlo and preserve auditable output contracts.
- **Requirements:** R9, R10.
- **Files:** `src/retirement_planner/simulators.py`, `src/retirement_planner/engine.py`, `src/retirement_planner/reports.py`, `tests/regression/test_mc_deterministic_parity.py`, `tests/integration/test_reports.py`, `tests/cli/test_cli_contracts.py`.
- **Approach:** Route both paths through the shared longevity-derived transition source without adding stochastic mortality or a new death-year API. Extend report rows/summary only with additive survivor and separate estate-tax fields, including post-estate net worth. Compare deterministic-equivalent MC output for alive state, normalized filing status, ACA/Medicare counts, survivor income, expense scaling, and estate timing; test RMD ownership separately in U3 rather than comparing deterministic numeric RMDs.
- **Test scenarios:** Existing longevity ages produce matching transition fields across paths; both death orders remain symmetric; housing-event tax receives normalized post-death status; JSON/Markdown reports expose survivor, separate estate, and post-estate net-worth fields; existing report consumers continue parsing current fields; numeric RMD parity is explicitly not asserted.
- **Verification:** MC parity regression, report integration tests, full core suite, and optional chart/PDF suites.

## Verification Contract

| Gate | Command or evidence | Applies to |
|---|---|---|
| Household contract | `python -m pytest -q tests/unit/test_household.py tests/regression/test_survivor_vertical.py` | U1–U3 |
| Tax/benefit integration | `python -m pytest -q tests/integration/test_engine_tax.py tests/unit/test_tax_law.py` | U2/U3 |
| MC parity | `python -m pytest -q tests/regression/test_mc_deterministic_parity.py` | U4; survivor fields only, not numeric RMDs |
| Report contracts | `python -m pytest -q tests/integration/test_reports.py tests/cli/test_cli_contracts.py` | U4 |
| Core release gate | `python -m pytest -q` | Every unit and final branch |
| Optional gates | `python -m pytest -q tests/cli/test_charts.py tests/cli/test_pdf_report.py` with extras installed | Final branch |
| Hygiene | `git diff --check`, inspect `git status --short`, review additive output fields | Final branch |

## Definition of Done

- U1–U4 are implemented without stochastic mortality or unrelated tax-law rewrites.
- Both death orders have golden fixtures and pass.
- Death-year MFJ and post-death filing transitions are proven.
- Survivor Social Security, all-expense ratio, separate ACA/Medicare counts, and RMD ownership are visible and tested.
- Estate tax is assessed once at second death, reported separately, reflected in final net cash flow, and represented through additive post-estate net-worth fields.
- Deterministic and longevity-derived Monte Carlo paths share survivor transition behavior; numeric deterministic RMD parity is not required.
- Equal death years use one combined/MFJ estate event; all tax calls, including housing-event tax, receive normalized `FilingStatus` values.
- Existing public output fields remain compatible; new fields are additive.
- Core and optional release gates pass.
- `git diff --check` passes, abandoned experiments are removed, and only intentional files are committed.
