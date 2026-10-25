# Mantissa project review — October 2026

This review builds on the existing, uncommitted October engine corrections and web chart work. It adds three bounded fixes and identifies the next engineering priorities. It does not change household assumptions or establish retirement readiness.

## Implemented corrections

### Spending strategies respect actual obligations

The old dynamic floor summed original recurring `is_must_spend` amounts. It omitted mortgages, mandatory one-time costs, age-event changes, real expense growth and nominal inflation. Percentage and floor/ceiling strategies repeated this calculation. Aggregate cuts could exceed the reductions allowed by the expense configuration.

The expense calculation now exposes each discretionary expense's remaining reduction allowance. The simulation converts that allowance to its active dollar convention and survivor scale, subtracts amounts already funded from nominated accounts, and protects the rest of current cash expenses. The current cash total already includes medical excess inflation and IRMAA. New purchase-year mortgage payments remain mandatory additions after the strategy calculation.

Dynamic, percentage, floor/ceiling and guardrail dispatch all respect this floor. The combined stress/strategy reduction cannot exceed `min_reduction`. An expense with `min_reduction: 0` has no reduction allowance, even when `is_must_spend` is false. This intentionally makes flexible-spending outcomes more restrictive. The strategy still returns an aggregate spending amount; category-by-category realization and deduction reconciliation remain follow-up work.

Tests cover mortgage obligations and payoff, mandatory one-time repairs, medical age events/growth/excess inflation, nominal spending, limited discretionary cuts, prior stress reductions and funded expenses.

### Browser results preserve model limitations

The browser bridge previously returned an empty `warnings` array, despite the native planner exposing missing-basis, forecast-date and account-access limitations. The bridge now preserves and deduplicates these messages as structured warnings. The viewer displays them before the KPIs and narrative. Older snapshots without warning messages remain renderable.

A native integration test executes the browser's embedded Python against the actual engine, and DOM tests check visible, safely escaped messages.

### Engine loading is atomic and retryable

The browser previously published the Pyodide instance before package installation and the import check finished. A dependency failure could leave `isReady()` true and retain a rejected bootstrap promise. The instance is now published only after initialization completes; a rejected attempt clears the shared promise. Concurrent callers share initialization. The plan store also retries initialization after a failed load instead of assuming the engine is ready.

The conservative access and monetary-accounting foundations below have since been implemented; see [access and accounting](access-and-accounting.md). Exception coverage, additional tax inputs and richer outcome reporting remain follow-up work.

## Prioritized follow-up backlog (review snapshot)

| Priority | Change | Acceptance criteria |
|---|---|---|
| P0 | Model accessible retirement funding | Separate economic liquidity from permitted spending access. Track account owner, Roth contribution/conversion cohorts, HSA qualified spending and explicit access policies. Report first access shortfall separately from portfolio depletion; run a young-retiree case with substantial restricted assets and insufficient taxable cash. |
| P0 | Correct nominal basis and debt through real-dollar projections | Maintain nominal tax basis and contractual mortgage balances/payments in explicit units. Convert only at simulation boundaries. Equivalent real and nominal configurations must produce matching nominal gains, tax bills, debt schedules and terminal real wealth. Cover inflation-only gains, refinancing, housing sale and mortgage payoff. |
| P0 | Make forecast-date reconciliation actionable | Require an explicit balance date for decision-grade results; detect a mismatch with the whole-year forecast start. Offer an opening-balance reconciliation workflow or a clearly provisional result. Do not silently prorate annual tax or duplicate completed cash flows. |
| P1 | Add taxable income yield and reconciliation | Model interest, qualified/nonqualified dividends, distributions and reinvestment basis without double-counting total return. Show effective tax and MAGI by source. Include withdrawals and conversions in healthcare-benefit calculations. |
| P1 | Separate spending, liquidity and legacy outcomes | Report cash-funding success, access success, spending-policy adherence and after-estate legacy success separately. Show years/depth of spending cuts, minimum taxable cash and realized spending by category. An inability to reach a legacy goal must not read as running out of money. |
| P1 | Apply spending changes to funded categories and deductions | Allocate aggregate adjustments to named categories before computing funding-account debits and deductions. Reconcile charitable/medical deductions and eligible premiums to actual adjusted spending. Add conservation tests for partial funding and mixed essential/discretionary categories. |
| P1 | Make equity compensation a first-class cohort model | Represent fixed shares versus fixed-dollar grants, vest dates, grant cancellation, withholding, sale fractions and liquidity events independently. Avoid requiring household-specific synthetic windfalls to represent retained shares and an IPO. Test share and basis conservation, delayed/no liquidity and grants after repricing. |
| P1 | Strengthen uncertainty and sequence reporting | Add paired stock/bond/CPI histories and explicit sequence stresses; identify cyclic wrapping and distinct historical sequences. Show sampling intervals for Gaussian results, while separating sampling error from model uncertainty. Expose common random seeds for scenario comparisons. |
| P2 | Improve assumption governance | Store units, as-of/source dates, confidence and household confirmation separately from amounts. Make real versus nominal growth explicit. Warn about ongoing expense streams ending before the horizon and unconfirmed major inputs. |
| P2 | Improve browser interpretation and resilience | Replace unconditional “over-saving” advice with conditional, goal-aware language. Preserve model/version/config hashes in exports; test full browser loading with the built wheel. Move long simulations to a worker and provide visible retry/cancel controls. Add web tests and builds to CI. |

Recommended order: finish the account-access and monetary-accounting foundations; then improve taxes, spending realization and outcome reporting; then extend compensation and stochastic realism. More simulation paths cannot repair missing cash obligations or incorrect units.

## Verification and release scope

The existing suite passed before these changes. Added regression cases reproduce failures in the previous spending implementation and pass after correction. Verification includes the complete Python suite, web unit/DOM tests and a production TypeScript/Vite build. Loading external Pyodide/CDN resources in a real browser remains a release check.

Changes are local and additive to the existing work in progress. No release, deployment, remote issue or pull request is created by this review. Private household inputs and scenario measurements belong outside the public repository.
