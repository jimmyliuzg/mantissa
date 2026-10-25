# Lightweight input refinement and realized spending

Mantissa keeps one annual simulation for the CLI and browser. Optional shortcuts
resolve once in Python (`config.readiness.resolve_inputs`) before Monte Carlo.
There are no new runtime dependencies, data services or monthly transaction
simulators. Existing configurations keep zero distribution yields unless they
explicitly opt in; their omissions are now visible in readiness results.

## Simple onboarding

The wizard still has nine steps. Savings can remain one total, or be separated
into cash, taxable brokerage, traditional retirement and Roth IRA balances.
Optional details stay inside the existing savings/spending steps. Total-only
savings use a taxable economic proxy: account access is **unassessed**, and the
browser suppresses account-access probabilities and balances. This shortcut
cannot establish that early-retirement withdrawals are available.

The wizard starts next January, carries entered balances unchanged to that
opening date, approximates dates from whole-year ages, assigns existing accounts
to the primary person and saves new surplus to cash/brokerage. It does not assume
new retirement-account contribution eligibility. Its initial legacy goal is $0,
shown in review and editable later. Retirement spending also applies during
working years until the user refines the expense dates. Spousal benefits start
at zero; the primary benefit estimate can be disabled explicitly.

The browser now emits canonical Social Security and return fields. Risk choices
change the allocation/glidepath under common stock and bond assumptions. The
editor uses the same canonical return fields. Shared fixtures are checked both
against the TypeScript builder and by loading/running the native Python engine.

## Input readiness

The resolved planner and simulation/report output expose `input_readiness`:

```json
{
  "provisional": true,
  "access_assessed": false,
  "items": [{"path": "balance_date", "status": "missing", "detail": "Confirm the statement date."}]
}
```

Each relevant field is `provided`, `estimated` or `missing`. Readiness records
input provenance/completeness; it does not independently verify statements or
certify tax accuracy. The result panel lists missing and estimated fields without
blocking exploration. Provisional results receive neutral wording. The CLI
prints a provisional label; JSON reports preserve the structured report.

Optional `input_metadata` has `account_breakdown` (`provided` or `missing`) and
`estimated_fields` (canonical paths such as `primary.birth_date` or
`accounts[0].cost_basis`). Curated editor changes clear only the matching estimate
marker. Advanced JSON users should maintain these markers when replacing
estimates. Changing an aggregate plan into actual accounts also requires setting
`account_breakdown` to `provided`.

Missing taxable basis keeps the existing opening-value fallback and is flagged;
missing Roth contribution principal is zero and its five-year clock stays
conservative. `unrealized_gain_fraction` optionally estimates taxable basis as
`balance * (1 - fraction)`; an explicit `cost_basis` always wins. For an unrealized
loss, enter exact/estimated dollar basis directly. A statement date does not
perform account reconciliation or interpolate completed-year cash flows.

## Investment income included in total return

Optional taxable-account fields are nominal annual fractions:

| Field | Meaning |
| --- | --- |
| `interest_yield` | Taxable ordinary interest |
| `dividend_yield` | Total dividends, including their qualified portion |
| `qualified_dividend_share` | Fraction of dividends eligible for preferential federal rates |
| `capital_gain_yield` | Long-term capital-gain fund distributions |
| `reinvest_distributions` | Default `true`; `false` makes distributions available as cash |

An optional `investment_income_profile` supplies illustrative defaults only:

| Profile | Interest | Dividends | Qualified share | Capital-gain distributions |
| --- | ---: | ---: | ---: | ---: |
| `none` | 0% | 0% | 0% | 0% |
| `stock_index` | 0% | 2% | 90% | 0% |
| `balanced` | 1.5% | 1.5% | 80% | 0% |
| `income` | 4% | 1% | 50% | 0% |
| `cash` | 3% | 0% | 0% | 0% |

These are modeling assumptions, not market quotes or product recommendations.
Explicit fields override profile defaults. Cash-profile total return, when not
specified, follows its nominal yield converted to real using general inflation.
Other profiles leave the account/portfolio total-return assumption unchanged.
Review the resolved percentages in readiness details and replace them as needed.

Distributions are calculated on opening nominal balances, after which the
simulator removes cash payouts from account value or adds reinvested payouts to
basis. They **never add another return** on top of total return. For example,
$1,000 growing to $1,060 with $20 of distributions leaves $1,040 invested plus $20
cash, or $1,060 invested with $20 additional basis. Taxes then reduce wealth
through the existing cash-flow/tax gross-up loop. A severe loss caps a distribution
at remaining assets. Retirement accounts compound internally without current
investment-income tax or additions to Roth regular-contribution principal.

Interest/nonqualified dividends are ordinary income; qualified dividends and
long-term fund distributions use federal preferential rates and ordinary CA
rates. Investment income enters modeled NIIT, Social Security provisional
income, ACA income and the IRMAA lookback. ACA counts full Social Security income.
Capital losses reduce MAGI only within the modeled annual deduction limit;
capital-loss carryforwards remain unsupported.

Annual `income` and `income_by_source` include cash distributions. Reinvested
amounts appear separately in `investment_income` and
`investment_income_by_account`, with ordinary/qualified/capital-gain/cash/reinvested
amounts. `qualified_dividends_nominal`,
`capital_gain_distributions_nominal`, `magi_nominal` and
`taxable_basis_nominal` expose the tax boundary.

Yields remain deterministic assumptions applied to sampled balances. Aggregate
basis, annual timing, fees, incomplete state coverage and existing healthcare
premium approximations still apply. Tax-exempt interest, return of capital,
short-term gain distributions, lot selection, holding-period verification and
loss carryforwards are outside this round.

Policy references: [IRS Publication 550](https://www.irs.gov/publications/p550)
for investment income and basis, and [Healthcare.gov income rules](https://www.healthcare.gov/income-and-household-information/income/)
for Marketplace income. The annual approximations above are Mantissa choices.

## Realized spending (priority 3)

A strategy first proposes aggregate spending. Mantissa distributes a reduction
proportionally over the **remaining permitted dollar cuts** of active expense
IDs, then debits nominated accounts and computes charitable deductions from those
actual amounts. Prior stress cuts consume the same allowance. Essential expenses,
mortgages, medical-inflation extras and IRMAA do not supply discretionary cuts.
Increases receive a separate strategy-adjustment line and do not invent tax
eligible giving. Duplicate display names aggregate only for reporting; funding
and tax classification use expense IDs.

Medical subsidy offsets are capped by actual remaining cash medical spending,
excluding expense amounts already paid by nominated accounts. Explicit
`tax_inputs` deduction overrides retain their existing precedence over inferred
expense deductions; users are responsible for updating such overrides.

Annual rows expose `planned_expenses` (before stress/strategy), `expenses_by_id`,
`expenses_by_category`, `spending_cut` and `spending_cut_fraction`. Named categories
sum to actual expenses in the active monetary convention. Monte Carlo exposes:

- `spending_cut_frequency`: share of runs with at least one annual cut over $1.
- `median_years_with_spending_cuts`: median number of years with such cuts per run.
- `maximum_spending_cut_fraction`: deepest annual total-budget cut observed across runs.

Cuts are measured against the planned total budget; a 25% cut to a 20% flexible
share is a 5% total-budget cut. Reported cuts are budget decisions, separate from
unfunded spending if the portfolio still cannot meet the reduced budget.
