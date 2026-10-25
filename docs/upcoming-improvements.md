# Upcoming improvements: priorities 4 and 5

Status: priority 4 is implemented; priority 5 remains scoped for a later round.
Priority 4 definitions and compatibility details are documented in
[separate goal outcomes](goal-outcomes.md). Priorities 1–3 are documented in
[input refinements and realized spending](input-refinements.md).

## Package 4 (implemented): Separate spending, account access and legacy outcomes

Problem: the compatibility `success` metric combines funded spending and the
terminal legacy goal. A high terminal balance can hide intervening funding gaps,
and a missed legacy goal can obscure fully funded spending.

Deliverables:

- Distinct spending-coverage, account-access and after-estate legacy outcomes,
  with explicit denominators, thresholds and monetary conventions.
- Planned versus realized spending alongside cut frequency, years and depth,
  so a run that needed reductions is visible even if its reduced budget cleared.
- First shortfall year and cause; access and depletion can overlap and are not
  additive probabilities. Unknown access stays unassessed.
- Browser, CLI and exported reports use the same outcome definitions. Keep the
  combined legacy metric for API compatibility and label its meaning clearly.
- Neutral result descriptions tied to the selected goals and input readiness;
  remove categorical claims about over-saving or retirement feasibility based
  solely on terminal wealth or the combined success rate.

Acceptance cases: spending covered with legacy missed; positive terminal wealth
with an early access gap; both access and economic shortfalls in one path;
spending covered only after cuts; incomplete account information; and equivalent
real/nominal scenarios. Existing shared annual calculations supply the data—no
second simulator or new onboarding requirement.

## Package 5: Native equity-compensation cohorts

Problem: existing grant/vesting support can estimate compensation income, but a
complete retained-share lifecycle needs grant ownership, tax basis and liquidity
constraints. Cash-equivalent vesting assumptions can overstate spendable assets.

Deliverables:

- Optional grant cohorts with owner, grant/vest dates, share counts, grant type,
  price assumptions and employment end conditions.
- Explicit sell-at-vest, sell-to-cover and hold policies. Separate wage income,
  actual withholding cash, retained shares and spendable sale proceeds.
- Aggregate retained-share basis and subsequent sale gains/losses. Withholding
  is a tax payment/credit rather than a reduction in the wage-income base.
- Optional refresher grants and explicit liquidity events/restrictions, with
  transparent concentration and valuation assumptions. Private shares cannot
  automatically fund ordinary spending before a liquidity event.
- Reconcile with existing account balances so vested/retained shares, proceeds
  and grants are never counted twice. Preserve existing legacy compensation
  configs with documented migration and approximation warnings.
- An optional advanced config/import workflow; the short onboarding path still
  requires no grant records. Use only fictional grant fixtures in the repository.

Acceptance cases: vest-and-sell; vest-and-hold then sell at a gain/loss;
sell-to-cover with withholding reconciled at tax settlement; termination before
vesting; refresher overlap; private-to-liquid transition; owner-specific taxation;
and deterministic/Monte Carlo and real/nominal conservation.

Implementation order: complete package 4's outcome definitions first, then add
cohorts behind optional fields and feed the same annual funding/tax loop.
