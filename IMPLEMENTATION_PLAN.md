# Mantissa Implementation Plan

## Current State Assessment

### What Works
- Basic year-by-year cash flow projection
- Monte Carlo simulation (Gaussian + historical return sequences)
- Account types with individual growth rates
- Income streams (W-2, passive, SS)
- Age-based expense events
- Discretionary vs fixed expense model
- Federal + California tax brackets (indexed to inflation)
- Social Security claiming optimizer (36 strategies)
- Roth conversion optimizer (bracket-filling)
- Scenario comparator
- Tax-aware withdrawal engine (RMD → taxable → tax-deferred → Roth)
- Cost basis tracking + capital gains tax
- IRMAA, SS taxation, NIIT
- ACA subsidies, estate tax
- Equity glidepath + bond tent
- Investment fees (expense ratios)
- Asset location suggestions
- 4 withdrawal strategies (fixed, guardrails, dynamic, percent-of-portfolio, floor/ceiling)
- Complete JSON config parser

### What's Still Missing

#### MAJOR (Phase 5)

1. **No 529 / education funding** — Education expenses exist as categories but no 529 account type or tax-advantaged growth
2. **No pension modeling** — Defined benefit pensions with survivor benefits not modeled
3. **No inherited IRA rules** — SECURE Act 10-year rule for inherited IRAs not modeled
4. **No annuity modeling** — Immediate or deferred annuities not modeled

#### MODERATE (Phase 6)

5. **No reporting/export** — No standard report generation, charts, or export
6. **No CLI interface** — No command-line tool for running plans
7. **No visualization** — No charts, graphs, or visual output
8. **No sensitivity analysis** — `ScenarioComparator.sensitivity_analysis()` is a stub
9. **No state tax beyond CA** — Only California and Texas are hardcoded
10. **No pension modeling** — Defined benefit pensions not modeled

---

## Implementation Plan

### Phase 1: Fix Core Logic Errors ✅ COMPLETE

- [x] 1.1 Fix inflation double-counting — expenses flat in real terms
- [x] 1.2 Build proper withdrawal engine — tax-aware drawdown order
- [x] 1.3 Mortgage amortization — deferred to future phase
- [x] 1.4 Implement contributions during working years
- [x] 1.5 Housing events — deferred to future phase
- [x] 1.6 Roth conversions — deferred to future phase
- [x] 1.7 Implement capital gains tax — LTCG rates + cost basis
- [x] 1.8 Implement RMDs — IRS Uniform Lifetime Table at age 73+
- [x] 1.9 Complete from_config() parser

**Commits:** 7cde57a, 8b616bd, 82236ca

---

### Phase 2: Tax & Healthcare Modeling ✅ COMPLETE

- [x] 2.1 Implement IRMAA — 2-year lookback, Part B/D tiers
- [x] 2.2 Implement Social Security taxation — up to 85% taxable
- [x] 2.3 Implement ACA / pre-Medicare healthcare subsidies
- [x] 2.4 Add tax bracket indexing — federal, LTCG, CA indexed to inflation
- [x] 2.5 Add NIIT — 3.8% on investment income > $250K
- [x] 2.6 Add estate tax — 40% above $27.22M exemption (indexed)

**Commits:** 8f05543, d989470

---

### Phase 3: Investment Modeling ✅ COMPLETE

- [x] 3.1 Implement equity glidepath — age-based allocation (90% at 30 → 40% at 80)
- [x] 3.2 Implement bond tent — 30% equity during 5yr pre/post retirement
- [x] 3.3 Add historical return sequences — 98 years S&P 500 (1926-2023)
- [x] 3.4 Add investment fees — expense ratio per account
- [x] 3.5 Add asset location modeling — tax-efficient suggestions

**Commits:** 4942ba3, 074db4d

---

### Phase 4: Withdrawal Strategies ✅ COMPLETE

- [x] 4.1 Implement guardrails spending — floor/ceiling bounds
- [x] 4.2 Implement dynamic spending — cut discretionary in stress
- [x] 4.3 Implement percent-of-portfolio — fixed % withdrawal
- [x] 4.4 Implement floor/ceiling — hard min/max spending

**Commit:** e2d4cb3

---

### Phase 5: Additional Account Types (TODO)

- [ ] 5.1 Add 529 / education accounts — tax-advantaged growth for education
- [ ] 5.2 Add pension modeling — defined benefit with survivor benefits
- [ ] 5.3 Add inherited IRA — SECURE Act 10-year rule
- [ ] 5.4 Add annuity modeling — immediate/deferred, fixed/variable

---

### Phase 6: Reporting & UX (TODO)

- [ ] 6.1 Generate standard reports — cash flow, account balances, taxes, net worth
- [ ] 6.2 Export formats — JSON, CSV, Markdown
- [ ] 6.3 Visualization — net worth trajectory, Monte Carlo fan chart
- [ ] 6.4 CLI interface — `mantissa run`, `mantissa compare`, `mantissa sensitivity`

---

## Feature Parity Benchmarking

| Feature | Boldin | ProjectionLab | Mantissa |
|---------|--------|---------------|----------|
| Monte Carlo simulation | ✅ | ✅ | ✅ Gaussian + Historical |
| Tax-aware withdrawals | ✅ | ✅ | ✅ RMD → taxable → tax-deferred → Roth |
| RMDs (age 73+) | ✅ | ✅ | ✅ IRS Uniform Lifetime Table |
| IRMAA (Medicare surcharges) | ✅ | ✅ | ✅ 2-year lookback, Part B/D tiers |
| Roth conversions | ✅ | ✅ | ✅ Bracket-filling optimizer |
| Capital gains (LTCG) | ✅ | ✅ | ✅ 0/15/20% + cost basis tracking |
| SS optimization | ✅ | ✅ | ✅ 36 claiming strategies + taxation |
| SS taxation | ✅ | ✅ | ✅ Up to 85% taxable |
| NIIT (3.8%) | ✅ | ✅ | ✅ On investment income > $250K |
| Tax bracket indexing | ✅ | ✅ | ✅ Federal, LTCG, CA indexed to inflation |
| ACA subsidies | ✅ | ✅ | ✅ Pre-Medicare with 400% FPL cliff |
| Estate tax | ✅ | ❌ | ✅ 40% above $27.22M (indexed) |
| Housing events | ✅ | ✅ | ⏳ Dataclass exists, not integrated |
| Healthcare costs | ✅ | ✅ | ✅ Age events + ACA + IRMAA |
| Equity glidepath | ❌ | ✅ | ✅ Age-based with bond tent |
| Historical returns | ❌ | ✅ | ✅ 98 years S&P 500 (1926-2023) |
| Dynamic spending | ✅ | ✅ | ✅ Spending rate monitoring |
| Guardrails | ❌ | ❌ | ✅ Floor/ceiling with portfolio triggers |
| Percent-of-portfolio | ✅ | ✅ | ✅ Fixed % with must-spend floor |
| Floor/ceiling | ✅ | ✅ | ✅ Coverage-ratio based |
| Investment fees | ❌ | ❌ | ✅ Expense ratio per account |
| Asset location | ❌ | ❌ | ✅ Tax-efficient suggestions |
| Age-based events | ✅ | ✅ | ✅ Healthcare, LTC, childcare |
| Discretionary vs fixed | ❌ | ❌ | ✅ Stress-testable expenses |
| 529 / education | ✅ | ✅ | ❌ Phase 5 |
| Pension modeling | ✅ | ✅ | ❌ Phase 5 |
| Inherited IRA | ❌ | ✅ | ❌ Phase 5 |
| Annuities | ✅ | ❌ | ❌ Phase 5 |
| CLI interface | ❌ | ❌ | ❌ Phase 6 |
| Reporting / export | ✅ | ✅ | ❌ Phase 6 |
| Visualization | ✅ | ✅ | ❌ Phase 6 |
| Sensitivity analysis | ✅ | ✅ | ❌ Stub |
| Open source | ❌ | ❌ | ✅ MIT License |

### Mantissa Differentiators
- **Open source** — MIT license (vs $120/yr Boldin, $96/yr ProjectionLab)
- **CLI / library** — Python package, not web-only
- **Real data integration** — Simplifi API for live account balances
- **Guardrails withdrawal** — Not available in any competitor
- **Asset location suggestions** — Not available in any competitor
- **Investment fee modeling** — Not available in any competitor
- **Configurable** — JSON configs, not locked to a UI
- **Python ecosystem** — pandas, numpy, matplotlib compatible

---

## Commit History

```
e2d4cb3 feat: add guardrails, dynamic, percent-of-portfolio, and floor/ceiling withdrawal strategies
074db4d feat: add historical return sequences and asset location suggestions
4942ba3 feat: add equity glidepath, bond tent, and investment fees
d989470 feat: add tax bracket indexing, ACA subsidies, and estate tax
8f05543 feat: add IRMAA, SS taxation, and NIIT
8b616bd fix: restore from_config() parser lost in engine rewrite
7cde57a fix: critical logic errors - inflation, withdrawals, contributions, RMDs, capital gains
82236ca feat: complete from_config() parser for all config sections
0431690 docs: comprehensive implementation plan with gap analysis
d325a27 refactor: rename to mantissa, remove Boldin references
b2afa25 Add discretionary expense model, stress scenarios, and age-based expense events
6d8d33e feat: reasonable default assumptions based on historical data
4241227 chore: finalize repo for public sharing
65a21fc feat: complete retirement planner with enhancements
```
