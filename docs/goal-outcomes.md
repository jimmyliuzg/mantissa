# Separate goal outcomes (priority 4)

Mantissa reports spending coverage, account access and legacy attainment
independently. These are observations of the same annual simulation, with no new
onboarding requirement, runtime dependency or second simulation engine.

## Definitions

| Outcome | Per-run definition |
| --- | --- |
| Planned spending met without cuts | Every adjusted budget was funded, with no annual net reduction of the planned expense budget above $1 in base-year purchasing power. |
| Adjusted budget funded | No annual required funding gap above that tolerance after applying the spending policy. Required funding includes modeled expenses, taxes and required housing-purchase funding. |
| No account-access gaps | No funding gap attributable to remaining restricted balances, under `penalty_free` access with actual account breakdown. Otherwise unassessed (`null`). |
| After-estate legacy target met | Final projected wealth after modeled federal estate tax meets or exceeds the configured terminal legacy target, independently of earlier funding gaps and budget cuts. |

"Planned" compares the actual simulated path with its pre-stress/pre-strategy
expense budget. If the strategy cut spending, this metric does not establish
whether the original budget could have been funded. No additional counterfactual
simulation runs. Adjusted expense budgets are decisions; they must still be
funded before the adjusted-budget outcome can pass. Spending coverage includes
the whole modeled horizon, including working years.

Access and economic shortfalls can coexist in one year. Conversely, access can
be clear while spendable capital is depleted. Their probabilities must not be
added or interpreted as substitutes for overall spending coverage. A
mortgage/down-payment purchase funding gap also prevents the adjusted-budget
outcome from passing, even when ordinary living expenses were funded.

A $0 legacy target has no positive bequest requirement. Meeting it says nothing
about earlier funding feasibility. Beneficiary income taxes on inherited
retirement accounts, state estate/inheritance taxes, lifetime-gift records and
trust/portability elections remain outside this aggregate projection.

## Result contract

`run_single_simulation` adds `outcomes` with:

- `schema_version: 1`, `base_year`, `final_year`, `monetary_convention` and
  `legacy_target_base_year`.
- `planned_spending_met`, `adjusted_spending_met`, `account_access_met` and
  `legacy_target_met` (access alone can be `null`).
- `first_funding_shortfall_year`, `first_funding_shortfall_causes` and
  `first_spending_cut_year`, each empty/null when absent.
- `legacy_target`, `legacy_shortfall`, `final_wealth_after_estate` and `estate_tax`,
  expressed in the active monetary convention at the final simulated year.
- `estate_tax_timing`: `annual_projection` for the existing two-person estate
  settlement, or `terminal_estimate` for single-household/stochastic runs.

The separate legacy outcome uses the existing versioned estate-tax calculator.
Single-household and stochastic paths have no two-person estate event, so their
legacy diagnostic estimates tax at the terminal year. This does not withdraw
cash or change their historical `estate_tax`, `net_worth_after_estate` or
`success` fields. Married deterministic paths reuse the existing assessment
without subtracting it twice. Both retain the engine's aggregate ownership and
exemption assumptions; this is not an estate-return calculation. See the
[IRS estate-tax overview](https://www.irs.gov/businesses/small-businesses-self-employed/estate-tax)
for the broader filing/valuation rules and elections beyond this model.

Annual rows add `funding_shortfall`, `housing_funding_shortfall`,
`funding_shortfall_causes`, `adjusted_spending_met`, `planned_spending_met` and
`account_access_met`. They retain planned expenses, adjusted expenses and cut
amounts from priority 3. Funding amounts use the row's real/nominal convention;
the $1 reporting tolerance grows with inflation in nominal rows.

Cause codes are `account_access`, `liquid_capital`, `housing_purchase`,
`unassessed_access` and `funding_gap` (small combined gaps that exceed the
aggregate tolerance). Causes describe funding gaps, not every reason for a
negative annual cash-flow number: withdrawals can fully fund a negative cash
flow. A later access/depletion event does not replace the recorded first gap.

Monte Carlo adds an `outcomes` object with the four corresponding `*_rate`
fields, `denominators`, `base_year`, `monetary_convention`,
`legacy_target_base_year`, `terminal_estate_estimate_runs`,
`first_funding_shortfall_year_counts` and
`first_funding_shortfall_cause_counts`. Spending and legacy use all simulations.
Access uses assessed simulations only; zero assessed simulations produces
`null`, never 0% or 100%. First-gap causes may overlap, while each failed run
contributes to exactly one first-gap year. A positive integer simulation count
is required.

Existing cut-frequency, median-years and maximum-depth statistics remain
available beside the outcomes. The cut threshold uses the same base-year-dollar
tolerance. All statistics are conditional on the supplied assumptions, horizon,
return model and input readiness.

## Compatibility and surfaces

Historical `success` and `success_rate` keep their existing joint calculation:
no historical out-of-savings flag, and final historical after-estate wealth
strictly greater than the legacy goal. Their labels now say "Combined success
(legacy)." The historical out-of-savings flag also includes ending with zero net
worth; the new coverage outcome tests actual funding gaps, so fully funding a
budget and ending at exactly zero can meet spending and a $0 legacy target while
historical combined success remains false. Terminal estate estimates above can
also explain differences between separate legacy and historical success values.

CLI `run`, Markdown/PDF reports, JSON summary/Monte Carlo exports and the browser
consume the same outcome definitions. CSV/project exports preserve annual
spending, access and funding details; Monte Carlo rates belong to the summary
outputs. The browser leads with four goal cards, explains the selected legacy
target, and offers optional annual budget and first-gap detail. Provisional
inputs remain marked. Older shared snapshots and report dictionaries display
separate outcomes as unavailable until recalculated; no new rates are inferred
from their combined success value.

The UI no longer labels a plan over-saving or recommends retirement changes
based on combined success or terminal wealth. Existing comparison/stress/
sensitivity tables label compatibility success explicitly.

## Verification

Fictional regressions cover funded spending with legacy missed, positive
terminal wealth with an early access gap, overlapping access/capital gaps,
funding after spending cuts, exact zero-wealth/zero-goal boundaries, unknown and
unrestricted access, housing purchase shortages, estate-tax timing, native/
browser report equivalence, old snapshots and real/nominal equivalence. No
household plan data is needed or included.
