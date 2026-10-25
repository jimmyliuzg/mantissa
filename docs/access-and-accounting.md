# Retirement access and monetary accounting

## Access policy and migration

`withdrawal_access_policy` defaults to `"penalty_free"`. This is a conservative annual spending-feasibility policy, not a complete distribution-tax engine. Existing scenarios can produce different outcomes with unchanged balances. `"unrestricted"` reproduces the earlier access assumption, with an explicit warning; it does not restore earlier accounting errors.

The default policy protects traditional retirement accounts until the owner's age 59½. Roth IRA regular-contribution principal is available first, followed by declared conversion principal in chronological order once its five-tax-year clock matures. At age 59½, conversion principal no longer needs the separate penalty clock; earnings require the age and first-contribution-year qualification clocks. Workplace Roth plans retain their own qualification clock and conservatively do not expose early principal. HSA funding requires an expense nominated to the HSA and `hsa_qualified: true`; the flag asserts that the expense qualifies. Nonqualified HSA spending is excluded before 65 and treated as ordinary income after 65. 529s remain limited to nominated expenses.

Because the core has annual cash flows, spending eligibility is evaluated at January 1. A midyear age threshold can therefore open access in the following annual row. A conversion made during a tax year becomes seasoned on January 1 five tax years later. The engine does not infer SEPP, separation-from-service, disability or inherited-account exceptions, nonqualified Roth distribution taxes, penalties, or nondeductible IRA basis. A blocked withdrawal means “not available under this modeled policy,” not that a distribution is legally impossible.

For a Roth IRA, declare opening records in **nominal dollars at the forecast opening**:

```json
{
  "id": "roth_a",
  "name": "Roth IRA — fictional example",
  "type": "roth_ira",
  "tax_treatment": "roth",
  "owner": "primary",
  "balance": 80000,
  "roth_contribution_basis": 20000,
  "roth_first_contribution_year": 2018,
  "roth_conversion_basis": [{"year": 2023, "amount": 15000}]
}
```

Allocate each account's remaining principal to it once; do not repeat a household-wide basis in several accounts. The engine aggregates IRA ordering by owner, never between spouses, and consumes principal once across trials and accounts. Declared conversion amounts represent fully taxable conversion principal; mixed taxable/nontaxable conversion ordering is not modeled. Newly modeled regular contributions and conversions update the ledger. Missing regular basis is zero. A missing first year uses the earliest declared conversion year, or the opening year if no conversion supplies evidence.

Recognized retirement account types infer their tax treatment when omitted; contradictory treatments are rejected rather than exposing restricted funds as taxable cash. A funding-account debit or a sourced windfall cannot bypass retirement access. Use the withdrawal, rollover and conversion events for those accounts. Configuration validation rejects restricted sources in generic windfalls/housing and retirement accounts nominated directly to ordinary expenses.

## Outputs

- `out_of_savings_year` retains its compatibility meaning: first year any required funding is not met, including access or purchase-funding failures.
- `access_shortfall_year` records the first funding gap attributable to remaining restricted capital.
- `portfolio_depletion_year` records the first economic-capital or purchase-funding shortage. Both failure types can occur in one path.
- Monte Carlo reports `access_failure_rate` and `portfolio_depletion_rate`. These overlap and must not be added together. The browser shows them separately under the default access policy.
- Annual rows expose taxable cash at opening, accessible and restricted spending balances before the final draw, withdrawals by account, funding shortfalls, and remaining conversion cohorts with nominal principal and seasoning years. Accessible balance is gross capital before the tax cost of withdrawing it.

`success` continues to require funded spending and the after-estate legacy goal. Access failure invalidates spending feasibility even when terminal wealth is large.

## Monetary units and timing

The price index is `(1 + inflation) ** (year - start_year)`; the base-year row has index 1. In that row investment growth uses real returns in both conventions. Later nominal rows include the index step as well as real growth. This avoids an extra first-year inflation gain relative to base-year income, expenses and tax conversion. Annual rows include that year's market growth and cash flows, while `get_account_balance` remains a simple elapsed-years estimate rather than the cash-flow projection API.

Opening account balances and tax basis are nominal opening amounts, which equal real amounts at index 1. Tax basis is not inflation indexed: internally its REAL representation is rebased each year so its nominal value stays fixed. Contributions create nominal basis at their transaction year's index. Proportional sales realize nominal gains, including inflation-only gains. Cash/checking withdrawals do not manufacture capital gains; optional bank interest and investment distributions are modeled as described in [input refinements](input-refinements.md).

Existing mortgage balances, monthly payments, reset payments and deduction debt limits are **nominal contractual amounts**. Debt amortizes in nominal dollars; expenses and liabilities are converted for reporting. A fixed nominal payment declines in real purchasing power. Rate resets do not increase payments by general inflation unless the supplied reset actually changes the contract payment.

Housing-event sale/purchase prices, costs and new mortgage amounts are **base-year purchasing-power scenario amounts**. The event converts them to its year's nominal dollars before statutory sale exclusions and loan origination. The new loan then becomes a fixed nominal contract. A taxable account used for the purchase realizes the gain on its funding sale. Net home-sale proceeds create basis in the receiving cash; property acquisition costs establish property basis. `taxable_basis_nominal`, `mortgage_balances_nominal`, `ordinary_income_nominal` and `capital_gains_nominal` make these boundaries inspectable.

Conversions use base-year purchasing-power schedules, like recurring expenses. Prior-year RMD references preserve their prior nominal year-end values. Social Security tax thresholds, ACA estimates and IRMAA amounts are evaluated in nominal units and converted back for real reports. The legacy goal is converted to the final row's convention.

## Verification and boundaries

Anonymous regressions compare equivalent real and nominal scenarios through inflation-only gains, partial sales, house sales, purchases/new loans, mortgage payoff and ARM resets, conversion cohorts, healthcare benefits, RMDs and common stochastic returns/fees. The tests verify modeled accounting relationships; they do not implement a tax return or all account exceptions. Fixed inflation, aggregate basis, annual execution, deterministic distribution yields and inherited-account treatment remain limitations.

Policy references: [IRS Publication 590-B](https://www.irs.gov/publications/p590b), [IRS Publication 969](https://www.irs.gov/publications/p969). These describe distribution rules; the engine's conservative annual approximation and unsupported exceptions are specified above.

## Privacy checks

Run `python scripts/check_privacy.py` for tracked and candidate files, or `--staged` to inspect exact Git-index contents. The CI privacy job runs the content check. It flags common private-document names, personal home paths, non-example email addresses, SSN-shaped identifiers and known credential patterns without echoing matched values. It cannot prove arbitrary numbers or images are anonymous; review example data before publication. Public copyright attribution, repository URLs and existing Git identities are separate from household financial data. This update does not rewrite historical commits.
