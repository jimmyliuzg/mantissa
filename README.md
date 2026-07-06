# Retirement Planner

A flexible retirement planning engine built in Python.

## Features

- **Account Growth Projections** — Model different account types with individual growth rates
- **Income & Expense Modeling** — Project cash flow with inflation adjustments
- **Tax Calculations** — Federal + state tax brackets
- **Monte Carlo Simulation** — Run thousands of scenarios to calculate success rates
- **Scenario Comparison** — Compare different retirement strategies
- **Roth Conversion Planning** — Optimize conversion timing
- **Social Security Modeling** — Claiming strategies and COLA adjustments

## Installation

```bash
pip install git+https://github.com/jimmyliuzg/retirement-planner.git
```

## Quick Start

```python
from retirement_planner import Planner, MonteCarloEngine

# Load from config file
planner = Planner.from_config("my_plan.json")

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
    "name": "John",
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
from retirement_planner import ScenarioComparator

# Create planners for different scenarios
planners = {
    "baseline": Planner.from_config("baseline.json"),
    "early_retire": Planner.from_config("early_retire.json"),
    "high_spending": Planner.from_config("high_spending.json"),
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

## License

MIT
