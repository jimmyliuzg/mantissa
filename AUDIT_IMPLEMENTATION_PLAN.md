# Mantissa Audit — Implementation Plan

Remaining findings after C1-C3 (completed). Ordered by priority.

---

## Phase 1: HIGH — Correctness Bugs

### H1: JSON parse error handling in from_config()
**File:** engine.py:433-613
**Fix:** Wrap `json.load(f)` in try/except, re-raise with filename context.
**Effort:** 5 min
**Risk:** Low — pure error messaging improvement

### H4: LTCG bracket stacking calculation
**File:** engine.py:914-932
**Fix:** Review bracket floor calculation against IRS Worksheet. Add unit test with known-answer test for MFJ brackets.
**Effort:** 1-2 hrs (needs research + test)
**Risk:** Medium — tax calculation is core to accuracy

### H5: Estate tax trigger uses wrong spouse longevity
**File:** engine.py:1684-1687
**Fix:** Change trigger from `younger_age >= primary.longevity_age` to `younger_age >= younger.longevity_age`.
**Effort:** 15 min
**Risk:** Low — straightforward logic fix

### H6: Dead code cleanup (8 locations)
**Files:** models.py, engine.py, reports.py, simulators.py, enhancements.py
**Fix:** Remove: `Account.project_balance()`, `get_account_balance()`, `_calculate_taxes_legacy()`, `generate_account_report()`, `TaxCalculator` (never wired in).
**Effort:** 30 min
**Risk:** Low — delete only, no behavior change

---

## Phase 2: MEDIUM — Correctness & Data Quality

### M1: Percentile calculation inconsistency
**File:** simulators.py:125-131
**Fix:** Use `int(n * 0.10)` consistently instead of mixing `//` and `int()`.
**Effort:** 10 min

### M2: Historical bond returns hardcoded at flat 2%
**File:** historical_data.py:41-43
**Fix:** Replace with actual historical bond real returns by decade or year.
**Effort:** 1 hr (data sourcing)
**Impact:** Significant — affects all historical simulations

### M3: Hardcoded family_size=2 for ACA subsidy
**File:** engine.py:1581, 1795
**Fix:** Add `family_size` to scenario parameters.
**Effort:** 30 min

### M4: SS COLA decoupled from inflation in sensitivity analysis
**File:** sensitivity.py:69-70
**Fix:** When `general_inflation` changes, also update `ss_cola`.
**Effort:** 15 min

### M6: No negative allocation validation
**File:** models.py:19-25
**Fix:** Add bounds check in `AssetAllocation.__post_init__`: each pct in [0, 1].
**Effort:** 10 min

---

## Phase 3: MEDIUM — Performance

### M5: Use numpy for MC returns
**File:** engine.py:1525
**Fix:** Replace `random.gauss` with `numpy.random.normal` for bulk generation.
**Effort:** 30 min
**Dependency:** numpy must become a dependency (likely already transitive)

### M7: _get_return_sequence list allocation
**File:** simulators.py:138-139
**Fix:** Use `itertools.islice` + `itertools.cycle` to avoid per-sim allocation.
**Effort:** 15 min

### M9: Deep-copy entire scenario per sensitivity point
**File:** sensitivity.py:31
**Fix:** Only copy the specific variable being tested, not entire scenario tree.
**Effort:** 30 min

---

## Phase 4: LOW — Code Quality

### L1: _fmt_money both branches identical
**File:** cli.py:18-22
**Fix:** Remove dead threshold branch.

### L2: Module-level import random
**File:** engine.py
**Fix:** Move to local import in run_single_simulation.

### L3: Inconsistent report return types
**File:** reports.py
**Fix:** Standardize return types across report functions.

### L4: plt.close(fig) error path leak
**File:** charts.py
**Fix:** Use try/finally to ensure fig is closed.

### L5: pyproject.toml missing test config
**Fix:** Add [tool.pytest.ini_options] and [tool.coverage] sections.

### L6: export_csv silent empty rows
**File:** reports.py
**Fix:** Log warning when no data.

---

## Phase 5: TESTS — Critical Gap

### T1: Engine unit tests (0 tests for core engine)
**Module:** engine.py
**Tests needed:**
- Tax bracket regression tests (known-answer for MFJ)
- RMD divisor edge cases (age 72, 73, 121+)
- `out_of_savings` detection
- Zero-balance edge handling
- Glidepath ramp interpolation
- Bond tent boundary conditions

### T2: Model validation tests
**Module:** models.py
**Tests needed:**
- AssetAllocation validation (sum, bounds)
- Scenario.to_dict()/to_json() round-trip

### T3: Historical data tests
**Module:** historical_data.py
**Tests needed:**
- get_historical_return range bounds
- Cyclical wrapping correctness

### T4: Enhancements tests
**Module:** enhancements.py
**Tests needed:**
- RothConversionOptimizer with known scenario
- SocialSecurityOptimizer claiming age calculations
- TaxCalculator known-answer tests

---

## Execution Order

```
Phase 1 (HIGH):     H1 → H5 → H6 → H4
Phase 2 (MED data): M6 → M1 → M4 → M3 → M2
Phase 3 (PERF):     M5 → M7 → M9
Phase 4 (LOW):      L1 → L2 → L3 → L4 → L5 → L6
Phase 5 (TESTS):    T1 → T2 → T3 → T4
```

Total estimated effort: ~8-10 hours
