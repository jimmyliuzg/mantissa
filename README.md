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
from retirementplanner import RetirementPlanner, MonteCarloEngine

planner = RetirementPlanner.from_config("myplan.json")
projections = planner.project_cashflow()

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
    "birthdate": "1980-01-01",
    "retirementdate": "2045-01-01",
    "longevityage": 95
  },
  "spouse": {
    "name": "Partner",
    "birthdate": "1982-01-01",
    "retirementdate": "2045-01-01",
    "longevityage": 95
  },
  "accounts": [
    {
      "id": "brokerage",
      "name": "Joint Brokerage",
      "type": "brokerage",
      "taxtreatment": "taxable",
      "balance": 300000,
      "growthrate": 0.07
    },
    {
      "id": "traditional_401k",
      "name": "Traditional 401(k)",
      "type": "401k",
      "taxtreatment": "pretax",
      "balance": 700000,
      "growthrate": 0.07
    },
    {
      "id": "roth_ira",
      "name": "Roth IRA",
      "type": "rothira",
      "taxtreatment": "roth",
      "balance": 150000,
      "growthrate": 0.07
    }
  ],
  "expenses": [
    {
      "id": "living",
      "name": "Living expenses",
      "monthlyamount": 7000,
      "startdate": "2026-01-01",
      "enddate": "2080-12-31",
      "category": "general",
      "ismustspend": true
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
| `familysize` | Household-size input for applicable scenarios |
| `legacygoal` | Desired residual estate value |

### Accounts

| Field | Description |
|---|---|
| `id` | Unique account identifier |
| `type` | `401k`, `tradira`, `rothira`, `brokerage`, `hsa`, `checking`, `realestate`, `vehicle`, or `other` |
| `taxtreatment` | `pretax`, `roth`, `taxable`, or `taxexempt` |
| `balance` | Current nominal account balance |
| `growthrate` | Return assumption used by the selected engine path |
| `contributionpriority` | Order for surplus savings allocation |
| `annualcontributioncap` | Contribution ceiling where applicable |
| `equitypct` | Optional account-level equity allocation override |

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

Includes deterministic scenarios such as the dot-com decline, global financial crisis, high inflation, early-retirement crash, and lost decade.

## Withdrawal and Tax Planning

Mantissa includes components for:

- Taxable, pretax, and Roth withdrawals
- Required minimum distributions
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

## Reproducibility

For reliable comparison and testing, record:

- Scenario configuration hash
- Tax-law version
- Code version
- Random seed
- Return model and historical-data provenance

A production run should be reproducible from this metadata.

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
2. Enforce deterministic random-number handling across Monte Carlo paths.
3. Strengthen tax-lot, RMD, guardrail, household coverage, and survivor-status correctness.
4. Centralize tax-law, benefits, and assumption versioning by plan year.
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
