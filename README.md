# Mantissa

Mantissa is an open-source, Python-based retirement planning engine for testing retirement readiness, spending plans, tax-aware withdrawals, and major financial decisions under uncertain markets.

It models household cash flow, account balances, taxes, investment returns, healthcare, Social Security, equity compensation, and retirement risks across deterministic projections, stress scenarios, historical sequences, and Monte Carlo simulations.

> **Status:** Active development. Mantissa is planning software, not tax, legal, investment, or fiduciary advice. Verify tax-sensitive decisions with a qualified professional.

## What Mantissa Models

- Taxable, traditional, Roth, HSA, cash, real-estate, and other account types
- Income from salary, bonuses, passive income, Social Security, pensions, and selected equity compensation
- Expenses, mortgages, windfalls, housing events, age-based events, and flexible spending
- Tax-aware withdrawals, Roth conversion plans, required minimum distributions, capital gains, tax lots, charitable giving, and QCD concepts
- Federal and state tax calculations through a versioned tax-law layer
- ACA, Medicare, IRMAA, medical inflation, long-term-care scenarios, and household lifecycle transitions
- RSUs, refresh grants, ESPP, NQSOs, and mega-backdoor Roth modeling components
- Asset allocation, glide paths, bond tents, correlations, tax-aware rebalancing, deterministic stress paths, historical return sequences, and Monte Carlo simulations
- Fixed, dynamic, guardrail, percentage-of-portfolio, and floor/ceiling spending approaches
- Scenario comparison, sensitivity analysis, charts, PDF/Markdown reports, decision traces, tax traces, threshold warnings, and reproducibility metadata

## Core Questions

Mantissa helps evaluate questions such as:

- Can this household retire on a chosen date?
- How much can the household spend while preserving an estate target?
- Which accounts should fund retirement spending first?
- Is a Roth conversion window valuable?
- How do Social Security timing, market losses, healthcare, or long-term care affect the plan?
- How does concentrated employer stock change retirement risk?
- What changes most improve projected plan resilience?

## Installation

```bash
pip install git+https://github.com/jimmyliuzg/mantissa.git
```

For local development:

```bash
git clone https://github.com/jimmyliuzg/mantissa.git
cd mantissa
pip install -e .
```

## Quick Start

Run a Monte Carlo simulation:

```bash
mantissa run --config myplan.json --simulations 10000
```

Generate a report:

```bash
mantissa report --config myplan.json --format markdown --output report.md
```

Compare scenarios:

```bash
mantissa compare --config1 baseline.json --config2 early-retirement.json
```

Run sensitivity analysis:

```bash
mantissa sensitivity --config myplan.json --variable inflation --values 0.02,0.025,0.03
```

## Python API

```python
from retirement_planner import RetirementPlanner, MonteCarloEngine

planner = RetirementPlanner.from_config("myplan.json")
projections = planner.project_cash_flow()

engine = MonteCarloEngine(planner)
results = engine.run(num_simulations=10_000)

print(f"Success rate: {results.success_rate:.1%}")
```

## Minimal Configuration

```json
{
  "name": "Example retirement plan",
  "state": "CA",
  "primary": {
    "name": "You",
    "birth_date": "1980-01-01",
    "retirement_date": "2045-01-01",
    "longevity_age": 95
  },
  "spouse": {
    "name": "Partner",
    "birth_date": "1982-01-01",
    "retirement_date": "2045-01-01",
    "longevity_age": 95
  },
  "accounts": [
    {
      "id": "brokerage",
      "name": "Joint Brokerage",
      "type": "brokerage",
      "tax_treatment": "taxable",
      "balance": 300000,
      "growth_rate": 0.07
    },
    {
      "id": "traditional_401k",
      "name": "Traditional 401(k)",
      "type": "401k",
      "tax_treatment": "pre_tax",
      "balance": 700000,
      "growth_rate": 0.07
    },
    {
      "id": "roth_ira",
      "name": "Roth IRA",
      "type": "roth_ira",
      "tax_treatment": "roth",
      "balance": 150000,
      "growth_rate": 0.07
    }
  ],
  "expenses": [
    {
      "id": "living",
      "name": "Living expenses",
      "monthly_amount": 7000,
      "start_date": "2026-01-01",
      "end_date": "2080-12-31",
      "category": "general",
      "is_must_spend": true
    }
  ]
}
```

See `examples/sample_config.json` for a fuller configuration.

## Inputs

### Household

| Field | Description |
|---|---|
| `primary`, `spouse` | Name, birth date, retirement date, longevity age |
| `state` | State used for state-tax and health-plan assumptions |
| `family_size` | Household-size input for applicable scenarios |
| `legacy_goal` | Desired residual estate value |

### Accounts

| Field | Description |
|---|---|
| `id` | Unique account identifier |
| `type` | `401k`, `tradira`, `rothira`, `brokerage`, `hsa`, `checking`, `realestate`, `vehicle`, or `other` |
| `tax_treatment` | `pre_tax`, `roth`, `taxable`, or `tax_exempt` |
| `balance` | Current nominal account balance |
| `growth_rate` | Return assumption used by the selected engine path |
| `contribution_priority` | Order for surplus savings allocation |
| `annual_contribution_cap` | Contribution ceiling where applicable |
| `equity_pct` | Optional account-level equity allocation override |

### Income and Expenses

Income streams support recurring pay, salary, bonus, passive income, Social Security flags, and selected equity compensation fields. Expenses support recurring or one-time costs, categories, fixed-versus-flexible flags, and minimum-reduction settings for stress cases.

### Planning Events

Mantissa supports mortgages, windfalls, housing events, Roth conversion schedules, age-based expense changes, Social Security settings, and glide-path configuration.

## Simulation Modes

### Deterministic Projection

Projects annual cash flow and balances under selected assumptions.

### Monte Carlo

Runs many return paths to estimate plan resilience and failure risk. Use an explicit seed when reproducibility matters.

### Historical Sequences

Replays historical-style return sequences to expose sequence-of-returns risk.

### Stress Scenarios

Stress testing models a behavioral pullback: at stress level *s* (0..1),
every discretionary expense (`is_must_spend: false`) is cut by
`min_reduction × s` (e.g. a travel budget with `min_reduction: 0.92` is
cut up to 92% at full stress).  Must-spend items (housing, groceries
floor, LTC) are untouched.

```bash
# Sweep stress levels and compare success rates
mantissa stress -c plan.json -n 500

# Single stress level on a normal run
mantissa run -c plan.json -n 1000 --stress 0.5

# Or bake it into the config
# "stress_level": 0.5
```

The `stress` command also lists which expenses get cut and by how much.
Cuts include discretionary one-time expenses, such as scheduled charitable
gifts; use `min_reduction: 1.0` to allow a complete pause. The cut applies
in every active year of the run, rather than activating automatically on a
market drawdown. It reduces modeled gifts and their tax deductions together.
Stress affects both Monte Carlo and the deterministic projection, so
the two paths stay consistent.

## Withdrawal and Tax Planning

Mantissa includes components for:

- Taxable, pretax, and Roth withdrawals
- Required minimum distributions

`withdrawal_strategy` controls how the engine sizes annual withdrawals
once you're retired. The `withdrawal_rate` field is consulted only by
two strategies:

- `percent_of_portfolio` — withdraw `withdrawal_rate` × portfolio value
  each year, floored at essential expenses.
- `floor_ceiling` — anchor the floor/ceiling bands around
  `withdrawal_rate` of the planned portfolio.

Other strategies (`fixed`, `guardrails`, `dynamic`) ignore
`withdrawal_rate` and pick a different size each year. Setting it
under those strategies triggers a `mantissa validate` warning so
the value doesn't silently no-op. If you want a constant real-dollar
withdrawal, use `withdrawal_strategy: "fixed"` and skip
`withdrawal_rate`; the engine will use base-spending as the anchor.
- Roth conversion schedules and bracket-filling logic
- Capital-gain harvesting and tax-lot selection
- QCD and charitable-giving concepts
- ACA and IRMAA threshold awareness
- Tax-aware rebalancing and asset-location recommendations

Tax, benefit, and withdrawal results depend on inputs, tax-law version, and module integration state. Treat outputs as scenario analysis rather than final tax advice.

## Reporting

Available outputs include:

- Year-by-year cash-flow projections
- Net-worth trajectory
- Income versus expense charts
- Tax breakdowns
- Monte Carlo fan charts and success summaries
- Sensitivity analysis
- Scenario comparison
- PDF, CSV, JSON, and Markdown report paths where supported
- Tax traces, decision traces, and threshold warnings

## Release Surface

The supported core path is the deterministic projection and JSON, CSV, or Markdown reporting available without optional extras. The `validate`, `schema`, `init`, `project`, `explain`, `run`, `report`, `compare`, and `sensitivity` CLI commands are covered by the core test gate.

Charts require `pip install mantissa[charts]`. PDF reports require `pip install mantissa[pdf]`; PDF coverage runs in a separate CI job.

Some model areas remain approximate or experimental and should not be treated as fully integrated planning advice: historical bond inputs are synthetic, annual/monthly event execution is not yet unified, and early-retirement access and full tax-return rules remain incomplete. Outputs are scenario analysis, not tax, legal, investment, or fiduciary advice.

## Reproducibility

When comparing runs, record:

- Scenario configuration hash
- Tax-law version
- Code version
- Random seed
- Return model and historical-data provenance

Full reproducibility metadata is an active development priority and is not yet guaranteed in every report.

## Architecture

Key modules include:

| Module | Responsibility |
|---|---|
| `engine.py` | Main retirement planning and simulation flow |
| `models.py` | Scenario, household, account, income, expense, and event models |
| `tax_law.py` | Tax-law calculations and tax policy data |
| `tax_lots.py` | Tax-lot tracking and realized-gain calculations |
| `optimizer.py` | Withdrawal and Roth-conversion decision logic |
| `portfolio.py` | Multi-asset return model, stress paths, allocation, and rebalancing |
| `household.py` | Mortality, survivor, health-care, and spending-phase models |
| `tech_comp.py` | RSU, ESPP, NQSO, and mega-backdoor Roth components |
| `historical_data.py` | Historical-sequence return inputs |
| `explain.py` | Traces, warnings, validation, and reproducibility metadata |
| `charts.py`, `pdf_report.py`, `reports.py` | Visualization and report generation |

## Current Development Priorities

1. Unify annual and monthly simulation components into one authoritative event loop.
2. Preserve reproducibility contracts as simulation components evolve.
3. Strengthen tax-lot, RMD, guardrail, household coverage, and survivor-status correctness.
4. Extend the versioned rules catalog to remaining benefits and assumptions.
5. Improve historical return data provenance and asset-class coverage.
6. Expand integration tests, audit ledgers, and report-level assumption disclosures.

## Limitations

- Model outputs are estimates, not guarantees.
- Tax rules, benefit rules, plan rules, and state rules change; validate current-year assumptions.
- Historical or simulated returns do not predict future returns.
- Advanced modules may require additional configuration and integration validation for production use.
- Complex tax, estate, equity-compensation, insurance, and legal decisions require professional review.

## License

MIT


### October 2026 calculation corrections

Deterministic projections and Monte Carlo now share the cash-flow implementation,
including saving, spending withdrawals, Roth conversions, rollovers and housing.
The core honors cash/equity/bond allocation, correlated market shocks, optional
aggregate cost basis, contribution schedules, dated vesting and mortgage reset
scenarios. Itemized deductions and employee pretax contributions flow into taxes;
2025/2026 federal and California income-tax amounts have been corrected.

See [calculation corrections and supported inputs](docs/calculation-corrections-2026-10.md)
for configuration examples, source citations, compatibility changes and limitations.
The model still requires consistent January opening balances; `balance_date` exposes
an incompatible as-of date but does not create a partial-year forecast.

### Retirement access and monetary accounting

The default `withdrawal_access_policy` is now `"penalty_free"`. It checks the
annual spending bridge using declared Roth IRA principal and conversion cohorts,
and conservatively restricts other retirement distributions. Projections and
Monte Carlo distinguish access failures from economic portfolio depletion.
`"unrestricted"` preserves the earlier access assumption and emits a warning.

Tax basis keeps its nominal value across inflation; mortgage balances, rates and
payments follow nominal contracts. Real-dollar reports convert these amounts at
the reporting boundary. Equivalent real and nominal scenarios are regression
tested through sales, purchases, ARM changes, conversions, RMDs and healthcare.

See [access and accounting conventions](docs/access-and-accounting.md) for input
units, clock assumptions, migration examples and remaining exceptions. Run
`python scripts/check_privacy.py --staged` before committing. CI also checks
private-file names, contact details, home paths and credential patterns.

### Optional input refinement

The browser keeps a total-savings shortcut, with optional account breakdown, tax basis, Roth principal, investment-income profiles and spending flexibility. Missing/estimated inputs are flagged and total-only account access remains unassessed. See [input refinements](docs/input-refinements.md) for calculation details and [delivered priority 4 and upcoming priority 5](docs/upcoming-improvements.md) for the next packages.

### Separate goal outcomes

Results now distinguish planned spending without cuts, funded adjusted budgets, account-access gaps and after-estate legacy attainment. The historical combined success metric remains available with an explicit compatibility label. See [goal outcome definitions](docs/goal-outcomes.md) for reporting thresholds, terminal estate estimates and old-snapshot behavior.

### Contribution correctness and future rules

Automatic IRA and HSA funding now checks annual limits, owner eligibility and
shared contribution pools. Traditional IRA funding requires supported deductible
treatment; nondeductible IRA basis is not modeled. Unknown eligibility produces
warnings and optional refinement prompts.

Annual tax and contribution inputs live in versioned JSON packs. Scenarios can
forecast indexed limits or apply dated tax and contribution overrides, including
temporary changes that revert after an end year. Results distinguish catalog
baselines, published fields, projections and user assumptions. See
[rules and policy forecasts](docs/rules-and-policy.md) and the
[example scenario](examples/policy_forecast.json).

Gaussian and historical Monte Carlo runs retain a replay seed, resolved-input
fingerprint, model version and rule provenance in exports and browser snapshots.
See [reproducibility](docs/reproducibility.md) for the replay contract.
