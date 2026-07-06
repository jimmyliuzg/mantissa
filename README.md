# Mantissa

An open-source retirement planner that helps you answer the question: **"Given my savings, spending, and market assumptions, will I run out of money?"**

Mantissa uses Monte Carlo simulation to run thousands of scenarios and calculate your probability of success. It models:

- **Investment growth** across multiple account types (401k, Roth, brokerage, real estate)
- **Income streams** (salary, RSUs, passive income, Social Security)
- **Expense flexibility** — discretionary vs fixed expenses that can be cut during stress
- **Age-based events** — healthcare costs, long-term care, kids' education
- **Tax-optimized withdrawals** — Roth conversion planning, bracket management
- **Withdrawal strategies** — fixed, dynamic, floor/ceiling approaches

Built for people who want to stress-test their retirement plan against realistic market assumptions, not optimistic ones.

## Quick Start

```bash
pip install git+https://github.com/jimmyliuzg/mantissa.git
```

```python
from retirement_planner import RetirementPlanner, MonteCarloEngine

# Load from config
planner = RetirementPlanner.from_config("my_plan.json")

# Run projection
projections = planner.project_cash_flow()

# Monte Carlo
mc = MonteCarloEngine(planner)
results = mc.run(num_simulations=10000)
print(f"Success Rate: {results['success_rate']:.1%}")
```

---

## Complete Variable Reference

### 1. Profile Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `primary.name` | string | — | Primary person's name |
| `primary.birth_date` | date | — | Date of birth |
| `primary.retirement_date` | date | — | Planned retirement date |
| `primary.longevity_age` | int | 90 | Age to plan until |
| `spouse.name` | string | — | Spouse's name |
| `spouse.birth_date` | date | — | Date of birth |
| `spouse.retirement_date` | date | — | Planned retirement date |
| `spouse.longevity_age` | int | 90 | Age to plan until |
| `legacy_goal` | float | $1,000,000 | Target estate value at end |
| `state` | string | "CA" | State for tax calculations |

### 2. Economic Assumptions

All rates are **real** (inflation-adjusted) unless noted.

| Variable | Default | Pessimistic | Optimistic | Historical | Source |
|----------|---------|-------------|------------|------------|--------|
| `inflation` | 2.5% | 3.0% | 2.0% | 3.0% | CPI (1913-2023) |
| `medical_inflation` | 4.0% | 5.0% | 3.0% | 5-7% | CMS/NHE data |
| `housing_appreciation` | 3.5% | 2.5% | 5.0% | 3.5-4.0% | Case-Shiller/FHFA |
| `investment_return_mean` | 7.0% | 5.0% | 9.0% | 7.0% | S&P 500 real (1926-2023) |
| `investment_return_volatility` | 15% | 20% | 10% | 15-20% | S&P 500 std dev |
| `ss_cola` | 2.5% | 3.0% | 2.0% | 2.5% | Tied to CPI-W |

**Important:** Forward-looking estimates from Vanguard/JPM suggest 5-7% real returns for the next decade. This planner defaults to 7% (historical median). Many planners use 8-9% which may be overly optimistic.

### 3. Account Types & Growth Rates

| Account Type | Tax Treatment | Default Growth | Notes |
|--------------|---------------|----------------|-------|
| `401k` | Pre-tax | 7.0% | Taxed on withdrawal |
| `roth_ira` | Roth (tax-free) | 7.0% | No tax on withdrawal |
| `trad_ira` | Pre-tax | 7.0% | Taxed on withdrawal |
| `hsa` | Tax-exempt | 7.0% | Triple tax advantage |
| `brokerage` | Taxable | 7.0% | Capital gains on sale |
| `checking` | Taxable | 1.5% | Cash/near-cash |
| `real_estate` | Taxable | 3.5% | Housing appreciation |
| `vehicle` | Taxable | -4.0% | Depreciating asset |
| `other` | Taxable | 2-5% | Custom rate |

**Account fields:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier |
| `name` | string | Display name |
| `type` | string | Account type (see above) |
| `tax_treatment` | string | pre_tax, roth, taxable, tax_exempt |
| `balance` | float | Current balance |
| `growth_rate` | float | Real annual return |
| `monthly_contribution` | float | Monthly contribution |
| `employer_match` | float | Employer match amount |
| `employer_match_limit` | float | Max employer match |
| `is_depreciating` | bool | True for vehicles |
| `liquid` | bool | Can be withdrawn from |

### 4. Income Streams

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | — | Unique identifier |
| `name` | string | — | Display name |
| `owner` | string | — | "primary" or "spouse" |
| `monthly_amount` | float | — | Monthly income |
| `start_date` | date | — | When income starts |
| `end_date` | date | — | When income stops |
| `growth_rate` | float | 0.0 | Annual growth (COLA) |
| `is_w2` | bool | true | W-2 employment income |
| `is_passive` | bool | false | Passive/investment income |
| `is_ss` | bool | false | Social Security |
| `goes_to_account` | string | "" | Account for contributions |

### 5. Expense Categories

| Category | Inflation Rate | Notes |
|----------|----------------|-------|
| `general` | General inflation | Most expenses |
| `medical` | Medical inflation | Healthcare costs |
| `housing` | Housing appreciation | Home-related |
| `food` | General inflation | |
| `childcare` | General inflation | Time-limited |
| `transportation` | General inflation | |
| `entertainment` | General inflation | |
| `charity` | General inflation | Giving |
| `education` | Education inflation | 529, tuition |

**Expense fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | — | Unique identifier |
| `name` | string | — | Display name |
| `monthly_amount` | float | — | Monthly expense |
| `start_date` | date | — | When expense starts |
| `end_date` | date | — | When expense stops |
| `category` | string | "general" | Category (see above) |
| `is_one_time` | bool | false | One-time expense |
| `one_time_amount` | float | 0 | Amount if one-time |
| `one_time_date` | date | null | Date if one-time |
| `is_must_spend` | bool | true | Fixed vs discretionary |

### 6. Discretionary vs Fixed Expenses

**NEW:** Expenses can be marked as `is_must_spend: false` to indicate discretionary spending. During stress scenarios, discretionary expenses can be cut.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `is_must_spend` | bool | true | Fixed (can't cut) vs discretionary |
| `min_reduction` | float | 0.0 | Maximum % reduction in stress (0-1) |

**Withdrawal model options:**

| Strategy | Description |
|----------|-------------|
| `fixed` | Same spending regardless of portfolio value |
| `floor_ceiling` | Maintain floor, cap at ceiling |
| `percent_of_portfolio` | Withdraw fixed % each year |
| `dynamic` | Cut discretionary when portfolio drops |

**Example:** If 50% of budget is discretionary:
- Normal: $20K/mo spending
- Stress: Can cut to $10K/mo (50% reduction)
- This dramatically improves success rate

### 7. Age-Based Expense Model

**NEW:** Expenses can be tied to specific ages or life events.

| Event | Typical Age | Typical Cost | Duration |
|-------|-------------|--------------|----------|
| Kids (daycare) | Birth - 5 | $2,000-5,000/mo | 5 years |
| Kids (college) | 18-22 | $20,000-80,000/yr | 4 years |
| Healthcare (pre-Medicare) | Retire - 65 | $500-1,500/mo | Varies |
| Healthcare (Medicare) | 65+ | $200-500/mo | Lifetime |
| Long-term care | 75+ | $5,000-10,000/mo | 2-5 years |
| Home maintenance | All | 1-2% of value/yr | Lifetime |
| Car replacement | Every 5-8 years | $30,000-60,000 | One-time |

**Age event fields:**

| Field | Type | Description |
|-------|------|-------------|
| `trigger_age` | int | Age when event occurs |
| `trigger_date` | date | Or specific date |
| `expense_id` | string | Which expense to modify |
| `new_amount` | float | New monthly amount |
| `duration_years` | int | How long to apply |

### 8. Mortgages

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier |
| `name` | string | Display name |
| `balance` | float | Current balance |
| `interest_rate` | float | Annual interest rate |
| `monthly_payment` | float | Monthly payment |
| `start_date` | date | When mortgage starts |
| `end_date` | date | When mortgage ends |
| `is_tax_deductible` | bool | Interest deductible |

### 9. Windfalls

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier |
| `name` | string | Display name |
| `amount` | float | Dollar amount |
| `date` | date | When it occurs |
| `goes_to_account` | string | Which account receives it |
| `is_taxable` | bool | Subject to income tax |

### 10. Social Security

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `primary_benefit_at_67` | float | $3,000/mo | Primary benefit at 67 |
| `primary_claiming_age` | int | 67 | When to claim |
| `spouse_benefit_at_67` | float | $2,500/mo | Spouse benefit at 67 |
| `spouse_claiming_age` | int | 67 | When to claim |
| `cola_rate` | float | 2.5% | Cost-of-living adjustment |

**Claiming age adjustments:**
- 62: 70% of full benefit
- 64: 80% of full benefit
- 67: 100% of full benefit
- 70: 124% of full benefit

### 11. Roth Conversions

| Field | Type | Description |
|-------|------|-------------|
| `source_account` | string | Traditional IRA/401k |
| `target_account` | string | Roth IRA |
| `start_date` | date | When to start converting |
| `end_date` | date | When to stop |
| `annual_amount` | float | Max annual conversion |
| `target_bracket` | float | Stay below this tax bracket |

### 12. Monte Carlo Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `num_simulations` | 10,000 | Number of scenarios |
| `return_volatility` | 15% | Std dev of returns |
| `correlation` | 0.0 | Asset class correlation |
| `sequence_risk` | enabled | Bad early years hurt more |

### 13. Withdrawal Strategy

| Setting | Default | Options |
|---------|---------|---------|
| `strategy` | "dynamic" | fixed, floor_ceiling, percent_of_portfolio, dynamic |
| `withdrawal_order` | "taxable_first" | taxable_first, tax_deferred_first, pro_rata |
| `floor` | $0 | Minimum annual spending |
| `ceiling` | unlimited | Maximum annual spending |
| `dynamic_cut_pct` | 20% | % to cut discretionary in stress |

---

## Default Assumptions (Conservative Baseline)

This planner uses **conservative defaults** based on historical data:

| Assumption | Value | Source |
|------------|-------|--------|
| Investment returns (real) | 7.0% | S&P 500 (1926-2023) |
| Return volatility | 15% | S&P 500 std dev |
| General inflation | 2.5% | Fed target / historical |
| Medical inflation | 4.0% | CMS projections |
| Housing appreciation | 3.5% | Case-Shiller/FHFA |
| SS COLA | 2.5% | Tied to CPI-W |
| Tax brackets | 2024 MFJ | IRS |
| Legacy goal | $1M | User-configurable |

**Conservative by design:**
- Many planners use 8-9% real returns (Moderate-Aggressive)
- This planner defaults to 7.0% real returns (historical median)
- At 8.8% returns, success rate might be ~88%
- At 7% returns, success rate drops to ~67% (more realistic)

---

## Sensitivity Analysis

How much does 1% change in each assumption affect success rate?

| Variable | 1% Change Impact | Notes |
|----------|------------------|-------|
| Investment returns | ±15-20% success | **Most sensitive** |
| Expenses | ±10-15% success | Second most sensitive |
| Retirement age | ±5-10% success | Each year matters |
| Inflation | ±3-5% success | Compounds over time |
| Healthcare costs | ±2-3% success | Significant after 65 |
| Tax rates | ±1-2% success | Moderate impact |

---

## Example Configurations

See `examples/sample_config.json` for a complete working example.

### Minimal Config

```json
{
  "primary": {"name": "You", "birth_date": "1990-01-01", "retirement_date": "2035-01-01"},
  "spouse": {"name": "Partner", "birth_date": "1990-01-01", "retirement_date": "2035-01-01"},
  "accounts": [{"id": "savings", "name": "Savings", "type": "brokerage", "balance": 100000}],
  "expenses": [{"id": "living", "name": "Living", "monthly_amount": 5000, "start_date": "2024-01-01", "end_date": "2080-01-01"}]
}
```

### With Discretionary Expenses

```json
{
  "expenses": [
    {"id": "housing", "name": "Housing", "monthly_amount": 2000, "is_must_spend": true},
    {"id": "food", "name": "Food", "monthly_amount": 800, "is_must_spend": true},
    {"id": "travel", "name": "Travel", "monthly_amount": 1000, "is_must_spend": false, "min_reduction": 0.5}
  ]
}
```

### With Age-Based Events

```json
{
  "age_events": [
    {"trigger_age": 65, "expense_id": "healthcare", "new_amount": 500},
    {"trigger_age": 75, "expense_id": "ltc", "new_amount": 5000, "duration_years": 3}
  ]
}
```

---

## License

MIT
