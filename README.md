# Retirement Planner

A flexible retirement planning engine built in Python.

## Features

- **Account Growth Projections** — Model different account types with individual growth rates
- **Income & Expense Modeling** — Project cash flow with inflation adjustments
- **Tax Calculations** — Federal + state tax brackets (supports all US states)
- **Monte Carlo Simulation** — Run thousands of scenarios to calculate success rates
- **Scenario Comparison** — Compare different retirement strategies
- **Roth Conversion Planning** — Optimize conversion timing
- **Social Security Modeling** — Claiming strategies and COLA adjustments

## Installation

```bash
pip install git+https://github.com/jimmyliuzg/retirement-planner.git
```

Or install locally for development:

```bash
git clone https://github.com/jimmyliuzg/retirement-planner.git
cd retirement-planner
pip install -e .
```

## Quick Start

```python
from retirement_planner import RetirementPlanner, MonteCarloEngine

# Load from config file
planner = RetirementPlanner.from_config("examples/sample_config.json")

# Run cash flow projection
projections = planner.project_cash_flow()
for p in projections[:10]:
    print(f"Age {p['primary_age']}: Net Worth ${p['net_worth']:,.0f}")

# Run Monte Carlo simulation
mc = MonteCarloEngine(planner)
results = mc.run(num_simulations=1000)
print(f"Success Rate: {results['success_rate']:.1%}")
```

## Configuration

Create a JSON config file with your plan details:

```json
{
  "name": "My Retirement Plan",
  "primary": {
    "name": "Person A",
    "birth_date": "1990-01-01",
    "retirement_date": "2030-01-01",
    "longevity_age": 90
  },
  "spouse": {
    "name": "Person B",
    "birth_date": "1990-01-01",
    "retirement_date": "2030-01-01",
    "longevity_age": 90
  },
  "accounts": [...],
  "income_streams": [...],
  "expenses": [...],
  "legacy_goal": 1000000
}
```

See `examples/sample_config.json` for a complete example.

## Scenarios

Compare different retirement strategies:

```python
from retirement_planner import RetirementPlanner, ScenarioComparator

# Create planners for different scenarios
planners = {
    "baseline": RetirementPlanner.from_config("baseline.json"),
    "early_retire": RetirementPlanner.from_config("early_retire.json"),
    "high_spending": RetirementPlanner.from_config("high_spending.json"),
}

# Compare
comparator = ScenarioComparator(planners)
mc_comparison = comparator.compare_monte_carlo()
```

## Account Types

| Type | Tax Treatment | Growth Rate |
|------|---------------|-------------|
| 401k | Pre-tax | Varies |
| Roth IRA | Tax-free | Varies |
| Traditional IRA | Pre-tax | Varies |
| Brokerage | Taxable | Varies |
| HSA | Tax-exempt | Varies |
| Real Estate | Taxable | Housing rate |
| Vehicle | Taxable | Depreciating |

## Economic Scenarios

Each rate has three scenarios:

| Rate | Optimistic | Mean | Pessimistic |
|------|-----------|------|-------------|
| Inflation | 2.0% | 2.5% | 3.0% |
| Medical Inflation | 2.7% | 3.4% | 4.0% |
| Housing Appreciation | 5.3% | 4.4% | 3.5% |
| Investment Returns | 10.6% | 8.8% | 7.0% |

## API Reference

### Classes

- **`RetirementPlanner`** — Main engine for projections and tax calculations
  - `from_config(path)` — Load from JSON config file
  - `project_cash_flow()` — Year-by-year cash flow projection
  - `calculate_net_worth(year)` — Net worth at a given year
  - `run_single_simulation()` — Single scenario projection
- **`MonteCarloEngine`** — Run thousands of random simulations
  - `run(num_simulations)` — Returns success rate and statistics
- **`ScenarioComparator`** — Compare multiple scenarios side by side
  - `compare_monte_carlo()` — Monte Carlo comparison across scenarios
  - `compare_cash_flow()` — Cash flow comparison across scenarios
- **`RothConversionOptimizer`** — Optimize Roth conversion timing
- **`SocialSecurityOptimizer`** — Optimize Social Security claiming strategies
- **`TaxCalculator`** — Federal + state tax calculations

## License

MIT
