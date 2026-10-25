# Calculation corrections — October 2026

This release corrects the core annual projection. It does not establish a particular household's retirement readiness. Regression fixtures contain fictional data; no financial records belong in this engine repository.

## Corrected behavior

- The JSON `monetary_convention` now reaches the Scenario; `start_year` fixes the calendar independently of the execution date. `balance_date` produces a warning when full-year flows do not match January opening balances.
- Deterministic `project_cash_flow` delegates to the volatility-free simulation. Withdrawals, employee savings, employer matches, windfalls, rollovers, conversions and housing transactions affect both views identically. Surplus that exceeds contribution caps is retained in liquid cash, including retirement income surpluses.
- `asset_class` controls allocation. Cash/checking, vehicles and real estate receive no stock-market shocks. Equity and bond shocks are shared across accounts rather than drawn independently per account. Historical S&P returns apply only to the equity sleeve; bonds use the configured CMA, not a historical bond series. Explicit zero real-estate growth is honored, as are optimistic/pessimistic CMAs.
- Supplied `cost_basis` initializes aggregate taxable basis. Partial liquidations use proportional basis, and sourced transfers preserve basis. New contributions and reinvested RMD surplus establish basis. This remains aggregate accounting, not tax-lot identification.
- Employee traditional 401(k) deferrals and HSA savings reduce federal taxable income. HSA contributions are added back for California. Elective deferrals share the owner's 401(k) statutory ceiling, require modeled wages, and stop when that owner has no active employment; scheduled zero caps stop contributions. Contributions and taxes are solved together rather than funding savings after computing tax on gross wages. Employer matches add assets without consuming employee cash. Explicit year-specific caps are nominal-dollar ceilings.
- Eligible charitable expenses, configured SALT and qualified mortgage interest reach the tax calculation. Federal and California deductions are separate. The 2026 charitable floor, SALT phaseout, 5.4% top-bracket itemized reduction, corrected AMT phaseout and preferential gains, state itemized limitation and California millionaire surtax are modeled. Deductions remaining after ordinary income also shelter capital gains. Employee Social Security, Medicare and Additional Medicare taxes use wages by owner. Payroll cafeteria-plan HSA exclusions, CA SDI and other payroll deductions remain outside this model.
- Unsourced taxable windfalls create income; gifts flagged non-taxable do not. Sourced transfers need an explicit `taxable_amount` for taxable K-1 or other income differing from cash. That distinction is surfaced in `model_warnings`. `taxable_kind` distinguishes ordinary income from capital gains; `wage_owner` optionally applies employee payroll tax to a wage event.
- Funded qualified expenses debit their nominated account once. In-kind charity can debit appreciated holdings without realizing a modeled capital gain. A nominated 529 can fund education costs. `expenses` reports full spending; `cash_expenses` reports the amount requiring current cash, and `funded_expenses` the amount debited directly.
- Rollovers occur before same-year conversions. Validation rejects transfers between different owners or incompatible tax treatments. Cohort-based RMD ages (including 75 for births from 1960) and prior-year-end balances replace a universal age-73/current-year-balance rule. Mandatory distributions occur even without a cash shortfall; their reinvested surplus does not count twice toward spending. Conversion processing reserves RMDs.
- Synthetic refresher grants respect the configured vesting delay. Explicit `first_vest_date` supports quarterly/monthly schedules. Employment ending mid-year does not cancel the entire year's earlier vests, and cancelled grants generate no income. Legacy cliff schedules remain approximate unless actual dated grants are supplied.
- A home sale removes the entire property account, pays only linked mortgages and supports selling costs. A purchase debits the full equity requirement plus closing costs; an underfunded purchase records a shortfall and fails the cash-feasibility check. Taxable sale gains join the normal annual tax calculation rather than a hard-coded rate. Old mortgage payments stop around the sale month; new loans amortize from the purchase year. `rate_changes` supports explicit rate/payment scenarios for an ARM; it does not forecast its index, caps or future resets.
- ACA cash-flow benefits are capped at the modeled eligible premium. `aca_subsidy` reports the amount actually used; `aca_subsidy_estimate` preserves the uncapped estimate. Net cash flow adds the applied benefit. The optimizer no longer adds NIIT twice to a tax score already containing it.

## Input examples

```json
{
  "start_year": 2026,
  "balance_date": "2026-01-01",
  "monetary_convention": "real",
  "tax_inputs": {
    "2026": {"salt_paid": 30000, "ca_property_tax": 12000,
             "charitable_limit_pct": 0.3}
  }
}
```

`tax_inputs` amounts use the active plan convention and are converted to nominal dollars for tax assessment. The year-specific object overrides computed charitable/mortgage deductions when supplied, so avoid duplicate inputs. State income taxes paid are not automatically inferred from computed tax liability; enter actual/planned SALT payment amounts. The charitable percentage limit is explicit; stock gifts to a public-charity DAF generally require the 30% AGI ceiling. Carryforwards are not implemented.

Optional account fields: `asset_class` (`cash`, `equity`, `bond`, `mixed`), `cost_basis`, `return_volatility`, `contribution_caps_by_year` (e.g. `{"2026":24500,"2027":0}`), and `contribution_end_date`. `growth_rate` retains its legacy real-return meaning; a zero real cash return does not imply a zero nominal bank yield. `economic.bond_return_volatility` defaults to 0.06 and `equity_bond_correlation` to zero. Reported volatility is a modeling assumption.

A charity expense uses `category: "charity"`, `tax_deductible: true`; an in-kind gift additionally uses `payment_kind: "in_kind"` and `funding_account`. The holding period, charity eligibility, fair-market value and basis records must support that treatment. A qualified education expense can designate the 529 with `funding_account`; the engine assumes nominated expenses are qualified and does not verify receipts.

A mortgage uses `deduction_kind` (`none`, `itemized`, `rental`), `deductible_debt_limit` (default $750k federal), `ca_deductible_debt_limit` (default $1m), and optional `rate_changes`: `[{"date":"2031-07-01","interest_rate":0.08,"monthly_payment":4200}]`. Limits are user-supplied loan eligibility assumptions, not a determination of refinance tracing or pre-2018 grandfathering. Multiple qualified loans require an appropriate allocation of debt limits.

Housing events accept `selling_costs`, `purchase_costs` and `exclusion_eligible`. Their new loan can use `mortgage_deduction_kind` and the same debt-limit fields as a mortgage; the default claims no new-loan interest deduction. The legacy default assumes §121 eligibility; set it false for a nonqualifying sale. New equity is derived from purchase price minus mortgage, not clamped to the available down payment. Missing cash is explicit debt/shortfall rather than manufactured equity.

## Sources and model limits

Federal income-tax tables and 2026 indexed amounts: [IRS Revenue Procedure 2025-32](https://www.irs.gov/irb/2025-45_IRB). Itemized/SALT/charitable computations: [IRS Publication 505, 2026](https://www.irs.gov/publications/p505). State schedules: [2024 FTB](https://www.ftb.ca.gov/forms/2024/2024-540-tax-rate-schedules.pdf), [2025 FTB](https://www.ftb.ca.gov/forms/2025/2025-540-tax-rate-schedules.pdf), [FTB October 2026 indexing](https://www.ftb.ca.gov/about-ftb/newsroom/tax-news/). State adjustments: [2025 Schedule CA instructions](https://www.ftb.ca.gov/forms/2025/2025-540-ca-instructions.html). Contribution limits: [IRS retirement limits](https://www.irs.gov/retirement-plans/cola-increases-for-dollar-limitations-on-benefits-and-contributions). Payroll rates: [SSA 2026 factsheet](https://www.ssa.gov/cola/factsheets/2026.html), [IRS Additional Medicare tax](https://www.irs.gov/taxtopics/tc560).

Future brackets/limits are projections, not published law tables. IRMAA/ACA premiums and several benefit inputs remain approximations. California credits, depreciation, passive-loss carryforwards, partnership basis/recapture, investment distributions, short-term gains, full AMT preferences, nondeductible IRA pro-rata basis and early-retirement access/penalties are not fully modeled. The subsequent [access and accounting update](access-and-accounting.md) defines nominal basis, contractual debt and housing-event units and adds equivalent real/nominal regressions. The conservative access policy covers declared Roth IRA clocks; exception and penalty modeling remain incomplete. No partial-year as-of forecast is implemented. `model_warnings` travels with simulation results and projection rows.

Regression tests exercise monetary conservation, deduction effects, payroll caps, liquidity, correlated shocks, basis, dated events and CLI/report compatibility. A passing test suite verifies the modeled relationships, not the completeness of a tax return.
