---
title: "Stochastic Mortality - Plan"
date: 2026-08-20
type: implementation-plan
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
---

# Stochastic Mortality — Implementation Plan

## Goal Capsule

- **Objective:** Add real actuarial death risk to Monte Carlo so each run samples a random household death year, producing probability distributions like "at age 80: X% dead, Y% out of money, Z% 3x+ target."
- **Architecture:** Replace the current fixed-longevity MC path with stochastic mortality sampling. Both spouses die together (simplified). The existing survivor transition machinery (filing status, SS, expenses, estate) fires at the sampled death year. Deterministic path keeps configured longevity for point estimates.
- **Key simplification:** Both partners die at the same time. No independent death ages, no survivor transitions — just "household alive" → "household dead." This collapses the survivor vertical's complexity into a single binary state change.

---

## Status

**Implemented — U1–U4 complete** (commit `e2ba7a8` on branch `feat/stochastic-mortality`; full suite 743 passed, deterministic path and survivor parity preserved).

- **U1.** SSA 2023 full `q(x)` tables (ages 0–119, by sex, from `ssa.gov/oact/STATS/table4c6.html`) replace the approximate 5-year buckets in `household.py`. `sample_death_age` now takes a seeded NumPy RNG; `expected_remaining_years` returns complete life expectancy (e65♂ = 18.12, e80♀ = 9.82).
- **U2.** Each Monte Carlo run samples one household death age from the primary's table (both spouses die together — synthetic `stochastic_alive_snapshot`, MFJ, no survivor transitions / rollover / estate). Deterministic path unchanged (`stochastic=False` default).
- **U3.** `MonteCarloEngine.run` aggregates an age-indexed outcome distribution — `mortality_distribution`: % dead / % out of money / % 3x target / median NW by age.
- **U4.** `mantissa run --stochastic` flag plus the `mortality_distribution` field in the report JSON.

**Coverage:** `tests/regression/test_stochastic_mortality.py` (SSA anchors, sampling centering, distribution monotonicity, seed determinism, deterministic-path-unchanged, CLI flag); `tests/unit/test_household.py` updated for the new table.

**Not built (deferred, per plan):** independent death ages, correlated death, health-adjusted mortality, partial-year timing.

## What Changes

### Current behavior (MC)
- Every run: primary dies at exactly `birth_year + longevity_age`, spouse at `birth_year + longevity_age`
- Survivor transitions fire at fixed years — same in every run
- Output: "94% success rate" (all runs have the same death timing)

### New behavior (MC)
- Each run: sample a death year from SSA actuarial tables
- Some runs: early death (age 65), some late (age 95)
- Output: "at age 80: 12% of runs have household dead, of those 8% ran out of money"

---

## Data Source

**SSA 2023 Period Life Table** (2026 Trustees Report):
- Source: https://www.ssa.gov/oact/STATS/table4c6.html
- Year-by-year death probabilities from age 0 to 119, separated by sex
- `q(x)` = probability of dying within one year at exact age x
- Currently in the codebase as approximate 5-year-bucket tables → replace with full SSA data

---

## Implementation Units

### U1. Replace mortality tables with SSA 2023 data

**Objective:** Full year-by-year death probabilities from the official SSA table, replacing the approximate 5-year interpolation.

**Files:**
- Modify: `src/retirement_planner/household.py` (replace `_MORTALITY_TABLE_MALE/FEMALE` with full SSA 2023 `q(x)` values)

**Approach:**
- Define `_SSA_QX_MALE` and `_SSA_QX_FEMALE` as dicts mapping age → `q(x)` (probability of death within one year)
- Ages 0-119 from the 2023 period life table
- `survival_probability(age)` = `1 - q(age)` (no interpolation needed — year-by-year data)
- Keep the `longevity_boost` parameter as an optional multiplier on survival probability
- Remove the old 5-year-bucket tables and `_interpolate_survival`

**Test scenarios:**
- Known values: q(65) male = 0.016455, q(80) female = 0.041183
- `expected_remaining_years(65, male)` ≈ 18.12 (matches SSA table)
- `expected_remaining_years(80, female)` ≈ 9.82 (matches SSA table)
- `sample_death_age` produces a distribution centered on life expectancy

**Verification:** `python -m pytest tests/unit/test_household.py`

---

### U2. Stochastic household death age in MC

**Objective:** Each MC run samples ONE death year for the household (both spouses die together). The existing survivor transition machinery is bypassed — instead, the household simply stops at the sampled death year.

**Files:**
- Modify: `src/retirement_planner/engine.py` (`run_single_simulation`)
- Modify: `src/retirement_planner/simulators.py` (pass RNG to sampling)

**Approach:**
- At the start of each MC run, sample a household death age using the **older** spouse's mortality table (conservative: the younger spouse's death is the binding constraint)
- Actually — since both die together, use the **primary's** mortality table (or average). Simplest: use the primary's table.
- Death year = `birth_year + sampled_death_age`
- In the MC loop, break when `year > death_year` (household is dead)
- No survivor transitions, no estate tax, no spousal rollover — just "alive → dead"
- The `survivor_snapshot()` call is replaced with a simple alive/dead flag derived from the sampled death year
- Deterministic path continues to use configured longevity (unchanged)

**Key detail:** The `MortalityModel` already has `sample_death_age()`. We use it, but with the full SSA tables from U1.

**Test scenarios:**
- MC with 1000 runs produces a distribution of death years (not all the same)
- Mean death year is close to SSA life expectancy
- Deterministic path is unchanged (still uses configured longevity)

**Verification:** `python -m pytest tests/regression/test_mc_survivor_parity.py` (deterministic still works), new stochastic tests

---

### U3. Aggregate outcome distributions by age

**Objective:** After running MC with stochastic mortality, produce the view the user actually wants: "at each age, what % of runs are dead, out of money, 3x+ target?"

**Files:**
- Modify: `src/retirement_planner/engine.py` (collect per-run death year + financial outcome)
- Modify: `src/retirement_planner/simulators.py` (aggregate across runs)
- Modify: `src/retirement_planner/cli.py` (new output format)

**Approach:**
- Each MC run returns: `death_year`, `final_net_worth`, `out_of_savings_year`, `success`
- Aggregate across runs into an age-indexed table:
  ```
  Age | % Dead | % Out of Money | % 3x+ Target | Median NW
  65  |   2%   |      0%        |     45%      | $2.1M
  70  |   5%   |      1%        |     52%      | $2.8M
  75  |  11%   |      3%        |     48%      | $3.1M
  80  |  20%   |      8%        |     35%      | $2.9M
  85  |  35%   |     15%        |     22%      | $2.4M
  90  |  55%   |     25%        |     12%      | $1.8M
  ```
- "Out of money" = `out_of_savings_year <= age` in that run
- "3x+ target" = `final_net_worth >= 3 * legacy_goal` in that run (or at time of death if dead)
- CLI: `mantissa run --config ... --stochastic` or new subcommand

**Test scenarios:**
- Aggregated percentages are monotonically increasing for "% Dead"
- Median NW peaks then declines (spending > growth in later years)
- All percentages sum sensibly (dead + alive-but-broke + alive-and-thriving ≤ 100%)

**Verification:** `python -m pytest tests/regression/test_stochastic_mortality.py`

---

### U4. Wire into CLI and reports

**Objective:** Expose stochastic mortality through the CLI and report output.

**Files:**
- Modify: `src/retirement_planner/cli.py`
- Modify: `src/retirement_planner/reports.py`
- Modify: `tests/cli/test_cli_contracts.py`

**Approach:**
- Add `--stochastic` flag to `mantissa run` (enables mortality sampling in MC)
- Add `mantissa mortality` subcommand (optional): shows the age-indexed outcome distribution
- Report JSON includes `mortality_distribution` field when stochastic mode is used
- Default behavior (no flag) remains the current fixed-longevity MC — backward compatible

**Test scenarios:**
- `mantissa run --config ... --stochastic --simulations 100` runs without error
- Output includes death year distribution
- Existing `mantissa run` (without `--stochastic`) behaves exactly as before

**Verification:** `python -m pytest tests/cli/test_cli_contracts.py`

---

## Verification Contract

| Gate | Command | Applies to |
|------|---------|------------|
| Unit tests | `python -m pytest tests/unit/test_household.py` | U1 |
| Stochastic MC | `python -m pytest tests/regression/test_stochastic_mortality.py` | U2, U3 |
| Parity (det unchanged) | `python -m pytest tests/regression/test_mc_survivor_parity.py` | U2 |
| CLI contracts | `python -m pytest tests/cli/test_cli_contracts.py` | U4 |
| Full suite | `python -m pytest -q` | All |

## Definition of Done

- SSA 2023 period life tables replace approximate tables
- Each MC run samples a random household death year
- Age-indexed outcome distribution is computed and displayed
- Deterministic path is unchanged (backward compatible)
- CLI exposes stochastic mode via `--stochastic` flag
- All existing tests pass; new tests cover stochastic behavior
- Output includes: % dead, % out of money, % 3x+ target, median NW by age

## What We're NOT Building (deferred)

- Independent death ages for each spouse (user simplified to "both die together")
- Correlated death (e.g., one spouse's death increases the other's mortality)
- Health-status-adjusted mortality (e.g., smoker/non-smoker)
- Partial-year death timing (death mid-year affects income/expenses)
