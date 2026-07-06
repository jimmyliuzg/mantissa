# Mantissa Implementation Plan

## Current State Assessment

### What Works
- Basic year-by-year cash flow projection
- Monte Carlo simulation (Gaussian returns)
- Account types with individual growth rates
- Income streams (W-2, passive, SS)
- Age-based expense events
- Discretionary vs fixed expense model
- Federal + California tax brackets
- Social Security claiming optimizer (36 strategies)
- Roth conversion optimizer (bracket-filling)
- Scenario comparator

### What's Broken or Missing

#### CRITICAL (Logic Errors)

1. **No withdrawal engine** — The simulation adds surplus to "brokerage - joint" by name match, but never actually withdraws from specific accounts in retirement. It just subtracts net_cash from total balance. No tax-aware drawdown order.

2. **Mortgages not amortized** — `calculate_net_worth()` estimates remaining balance as `balance * (1 - years / total_years)` (linear), not proper amortization. Real mortgage paydown is front-loaded interest.

3. **Taxes don't account for withdrawal source** — `calculate_taxes()` taxes total income, but doesn't distinguish between ordinary income (401k withdrawals), tax-free (Roth), and capital gains (brokerage). All treated as ordinary income.

4. **No capital gains modeling** — Selling from brokerage accounts triggers capital gains taxes. Not modeled.

5. **No RMDs** — Required Minimum Distributions from pre-tax accounts at age 73 are not modeled. This is a legal requirement that forces withdrawals and taxes.

6. **No contributions during working years** — 401k/HSA/IRA contributions are defined in income streams but never actually credited to account balances during the simulation.

7. **Housing events not integrated** — HousingEvent dataclass exists but is never processed in the simulation loop. Buying/selling homes doesn't happen.

8. **Roth conversions not integrated** — RothConversion dataclass exists, optimizer generates plans, but the simulation loop doesn't execute conversions (moving money from trad→Roth, paying tax).

9. **from_config() only parses accounts** — Income streams, expenses, mortgages, windfalls, age events, etc. are all left as empty lists with TODO comments.

10. **Inflation is real but expenses inflate too** — Growth rates are real (inflation-adjusted), but `calculate_annual_expenses()` also applies inflation. This double-counts inflation: expenses are inflated AND returns are real. Either expenses should stay flat (in real terms) or returns should be nominal.

#### MAJOR (Missing Features vs State of the Art)

11. **No IRMAA modeling** — Medicare surcharges based on income (2-year lookback) are a significant retirement cost. Tiers from $1,148 to $6,936/person/yr.

12. **No equity glidepath / bond tent** — Asset allocation should shift more conservative as retirement approaches. All accounts use a fixed growth rate.

13. **No sequence of returns risk mitigation** — The Monte Carlo runs Gaussian random returns, but doesn't model strategies to mitigate bad early years (cash buffer, bond tent, dynamic spending).

14. **No historical return sequences** — ProjectionLab uses actual historical market data sequences. We only use Gaussian approximation.

15. **No estate tax** — Federal estate tax exemption ($13.6M) and state estate/inheritance taxes not modeled.

16. **No state tax beyond CA** — Only California and Texas are hardcoded. No general state tax calculator.

17. **No ACA/Premium Tax Credit** — Healthcare costs before Medicare (age 65) should model ACA subsidies that phase out with income.

18. **No pension modeling** — Defined benefit pensions with survivor benefits not modeled.

19. **No inherited IRA rules** — SECURE Act 10-year rule for inherited IRAs not modeled.

20. **No 529 / education funding** — Education expenses exist as categories but no 529 account type or tax-advantaged growth.

#### MODERATE (Accuracy Improvements)

21. **Social Security taxation** — Up to 85% of SS benefits are taxable at certain income levels. Not modeled.

22. **NIIT (Net Investment Income Tax)** — 3.8% surtax on investment income over $250K (MFJ). Not modeled.

23. **Tax bracket indexing** — Brackets are hardcoded to 2024. They should be indexed to inflation.

24. **No asset location optimization** — Which assets go in which accounts (tax-efficient placement).

25. **No rebalancing model** — Portfolio drift and rebalancing aren't modeled.

26. **No fees/expense ratios** — Investment fees reduce returns. Not modeled.

27. **No inflation differentiation by category** — All non-medical expenses use general inflation. Education, transportation, and other categories have different inflation rates.

28. **Sensitivity analysis is a stub** — `ScenarioComparator.sensitivity_analysis()` returns empty dicts.

29. **No output/reporting** — No standard report generation, charts, or export.

---

## Implementation Plan

### Phase 1: Fix Core Logic Errors (Week 1-2)

#### 1.1 Fix inflation double-counting
- **Problem:** Returns are real (inflation-adjusted) but expenses are also inflated
- **Solution:** Since returns are real, keep expenses flat in real terms. Remove inflation from `calculate_annual_expenses()` OR switch to nominal returns + nominal expenses.
- **Decision:** Keep real returns, make expenses flat (real). The inflation rate is already embedded in the real return assumption.

#### 1.2 Build proper withdrawal engine
- **Problem:** Net cash flow is just added/subtracted from total balance
- **Solution:** Implement `WithdrawalEngine` class that:
  - Calculates required RMDs first (pre-tax accounts, age 73+)
  - Withdraws from taxable accounts first (tax-efficient order)
  - Then tax-deferred (401k, trad IRA)
  - Then Roth (last resort)
  - Calculates capital gains on brokerage sales
  - Tracks cost basis per account

#### 1.3 Implement mortgage amortization
- **Problem:** Linear paydown estimate
- **Solution:** Standard amortization formula: `remaining = P * [r*(1+r)^n - (1+r)^p] / [(1+r)^n - 1]`
  - P = principal, r = monthly rate, n = total payments, p = payments made

#### 1.4 Implement contributions during working years
- **Problem:** Contributions defined but never credited
- **Solution:** In simulation loop, for each year before retirement, add monthly_contribution * 12 + employer_match * 12 to account balances

#### 1.5 Integrate housing events
- **Problem:** HousingEvent exists but never processed
- **Solution:** In simulation loop, when year matches event date:
  - Sell current property (add proceeds to brokerage)
  - Buy new property (subtract down payment, create new mortgage)
  - Update account balances

#### 1.6 Integrate Roth conversions
- **Problem:** Optimizer generates plans but simulation doesn't execute them
- **Solution:** In simulation loop, for each year with a planned conversion:
  - Move amount from source (trad IRA/401k) to target (Roth)
  - Add conversion amount to taxable income
  - Recalculate taxes including conversion

#### 1.7 Implement proper capital gains tax
- **Problem:** All withdrawals taxed as ordinary income
- **Solution:** For brokerage withdrawals:
  - Track cost basis
  - Calculate realized gain = sale price - cost basis
  - Apply long-term capital gains rates (0%, 15%, 20% based on income)
  - Add NIIT (3.8%) if income > $250K

#### 1.8 Implement RMDs
- **Problem:** Not modeled at all
- **Solution:** At age 73, calculate RMD:
  - `rmd = balance / life_expectancy_factor` (IRS Uniform Lifetime Table)
  - Force withdrawal from pre-tax accounts
  - Add to taxable income
  - If not withdrawn, apply 25% penalty

#### 1.9 Complete from_config() parser
- **Problem:** Only accounts are parsed
- **Solution:** Parse all config sections: income_streams, expenses, mortgages, windfalls, housing_events, roth_conversions, age_events, social_security

---

### Phase 2: Tax & Healthcare Modeling (Week 3-4)

#### 2.1 Implement IRMAA
- 2-year lookback: current year premiums based on MAGI from 2 years prior
- Tiers: $1,148 to $6,936 per person per year
- Apply as expense at age 65+
- Model both Part B and Part D surcharges

#### 2.2 Implement Social Security taxation
- Calculate provisional income
- If provisional income > $44K (MFJ): 85% of SS is taxable
- Add taxable portion to AGI

#### 2.3 Implement ACA / pre-Medicare healthcare
- Model ACA premiums with subsidy phaseout
- Subsidies reduce as income increases (cliff at 400% FPL)
- Apply from retirement to age 65

#### 2.4 Add tax bracket indexing
- Index brackets to inflation rate
- Update each year: `bracket_limit * (1 + inflation) ** years`

#### 2.5 Add NIIT (Net Investment Income Tax)
- 3.8% on investment income over $250K MFJ
- Apply to capital gains, dividends, interest

#### 2.6 Add estate tax
- Federal: 40% above $13.6M exemption (2024, indexed)
- State: Varies (CA has no estate tax)
- Calculate at end of plan

---

### Phase 3: Investment Modeling (Week 5-6)

#### 3.1 Implement equity glidepath
- Define allocation by age: e.g., 90/10 at 30, 80/20 at 40, 70/30 at 50, 60/40 at 60
- Each allocation has different expected return and volatility
- Recalculate growth rate each year based on current allocation

#### 3.2 Implement bond tent
- Increase bond allocation 5-10 years before and after retirement
- Reduces sequence of returns risk
- Then gradually increase equity again

#### 3.3 Add historical return sequences
- Load historical S&P 500 / bond returns by year
- Run Monte Carlo using actual sequences (rolling 30-year windows)
- Compare with Gaussian approximation

#### 3.4 Add investment fees
- Configurable expense ratio per account (e.g., 0.03% for index funds)
- Reduces net return: `actual_return = gross_return - fee`

#### 3.5 Add asset location modeling
- Bonds in tax-deferred (ordinary income tax)
- Stocks in taxable (capital gains rate)
- Tax-exempt bonds in taxable
- Calculate blended return based on allocation

---

### Phase 4: Withdrawal Strategies (Week 7-8)

#### 4.1 Implement guardrails spending
- Calculate spending floor and ceiling
- Floor: 95% of prior year spending
- Ceiling: based on portfolio performance
- Adjust spending within guardrails each year

#### 4.2 Implement dynamic spending
- Reduce discretionary spending when portfolio drops below threshold
- Increase when portfolio exceeds threshold
- Configurable thresholds and adjustment rates

#### 4.3 Implement percent-of-portfolio
- Withdraw fixed percentage each year (e.g., 4%)
- With guardrails to prevent spending collapse

#### 4.4 Implement floor/ceiling
- Hard floor: minimum spending (survival level)
- Hard ceiling: max spending (lifestyle cap)
- Withdrawals adjust within bounds

---

### Phase 5: Additional Account Types (Week 9)

#### 5.1 Add 529 / education accounts
- Tax-advantaged growth for education
- Qualified withdrawals are tax-free
- Non-qualified withdrawals: 10% penalty + tax on earnings

#### 5.2 Add pension modeling
- Define benefit amount, start age, survivor benefit %
- COLA adjustments
- Pension funding ratio (for underfunded pensions)

#### 5.3 Add inherited IRA
- 10-year rule (SECURE Act)
- Required withdrawals within 10 years of inheritance
- Taxed as ordinary income

#### 5.4 Add annuity modeling
- Immediate or deferred
- Fixed or variable
- Payout rate and period certain

---

### Phase 6: Reporting & UX (Week 10)

#### 6.1 Generate standard reports
- Cash flow projection (year-by-year)
- Account balances over time
- Tax summary by year
- Net worth trajectory
- Success rate with percentiles

#### 6.2 Export formats
- JSON (structured data)
- CSV (spreadsheet)
- Markdown (readable)

#### 6.3 Visualization
- Net worth trajectory chart
- Income vs expenses overlay
- Monte Carlo fan chart (percentiles)
- Account balance breakdown

#### 6.4 CLI interface
- `mantissa run my_plan.json`
- `mantisa compare plan1.json plan2.json`
- `mantissa sensitivity plan.json --variable returns --range 0.05 0.07 0.09`
- `mantissa roth-optimize plan.json`

---

## Priority Ranking

### Do First (Critical Fixes)
1. Fix inflation double-counting (1.1)
2. Build withdrawal engine (1.2)
3. Implement contributions (1.4)
4. Implement capital gains tax (1.7)
5. Implement RMDs (1.8)
6. Complete from_config() (1.9)

### Do Second (Major Features)
7. Integrate housing events (1.5)
8. Integrate Roth conversions (1.6)
9. Implement IRMAA (2.1)
10. Implement SS taxation (2.2)
11. Tax bracket indexing (2.4)
12. Equity glidepath (3.1)
13. Historical returns (3.3)
14. Dynamic spending (4.2)

### Do Third (Polish)
15. Mortgage amortization (1.3)
16. ACA modeling (2.3)
17. NIIT (2.5)
18. Estate tax (2.6)
19. Bond tent (3.2)
20. Investment fees (3.4)
21. Reporting (6.1-6.4)

---

## Benchmarking

### Target Feature Parity

| Feature | Boldin | ProjectionLab | Mantissa (current) | Mantissa (target) |
|---------|--------|---------------|--------------------|--------------------|
| Monte Carlo | ✅ | ✅ | ✅ (Gaussian) | ✅ (Gaussian + historical) |
| Tax-aware withdrawals | ✅ | ✅ | ❌ | ✅ |
| RMDs | ✅ | ✅ | ❌ | ✅ |
| IRMAA | ✅ | ✅ | ❌ | ✅ |
| Roth conversions | ✅ | ✅ | ❌ (stub) | ✅ |
| Capital gains | ✅ | ✅ | ❌ | ✅ |
| SS optimization | ✅ | ✅ | ✅ (basic) | ✅ (with taxation) |
| Housing events | ✅ | ✅ | ❌ (stub) | ✅ |
| Healthcare costs | ✅ | ✅ | ❌ (stub) | ✅ |
| Historic returns | ❌ | ✅ | ❌ | ✅ |
| Equity glidepath | ❌ | ✅ | ❌ | ✅ |
| Dynamic spending | ✅ | ✅ | ❌ (stub) | ✅ |
| Guardrails | ❌ | ❌ | ❌ | ✅ |
| Estate tax | ✅ | ❌ | ❌ | ✅ |
| Age-based events | ✅ | ✅ | ✅ (basic) | ✅ |
| CLI | ❌ | ❌ | ❌ | ✅ |
| Open source | ❌ | ❌ | ✅ | ✅ |

### Our Differentiators
- Open source (vs $120/yr Boldin, $96/yr ProjectionLab)
- CLI / library (vs web-only)
- Real data integration (Simplifi API)
- Configurable (JSON configs, not locked to a UI)
- Python ecosystem (pandas, numpy, matplotlib)