---
title: "Release Foundation - Plan"
date: 2026-08-18
type: implementation-plan
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-brainstorm
execution: code
---

# Release Foundation - Plan

## Goal Capsule

- **Objective:** Make Mantissa installable, testable, documented, and CI-verified as an alpha release without expanding retirement-model scope.
- **Authority:** Product scope selected during release-readiness brainstorm; existing code and tests define current behavior.
- **Stop condition:** Default tests pass, optional PDF coverage runs separately, clean installation smoke-tests successfully, package version is single-source and consistent, and README quick start is executable.
- **Execution profile:** Small sequential units; keep one writer and preserve current model behavior.
- **Tail ownership:** Survivor modeling and deeper correctness work remain follow-on scope.

## Product Contract

### Summary

Mantissa has broad working functionality but cannot claim release readiness while its default test gate fails, core dependencies are incomplete, version metadata conflicts, CI is absent, and the primary configuration example is not parser-compatible.

### Problem Frame

Users and maintainers need one reliable installation and verification path. Optional features must remain optional without making the default gate red. Documentation must show configuration accepted by the current validator.

### Requirements

- R1. Default `python -m pytest -q` passes without requiring optional PDF dependencies.
- R2. A separate verification path installs PDF dependencies and runs all PDF tests.
- R3. Every runtime dependency imported by core projection and simulation code is declared in the package's core dependencies.
- R4. Package metadata, `retirement_planner.__version__`, CLI version output, and the current changelog release agree on one release version.
- R5. CI verifies the supported Python range with core dependencies and verifies optional PDF behavior in a dedicated job.
- R6. A clean-install smoke check installs the built package rather than relying on the repository checkout and runs a minimal CLI projection.
- R7. README minimal configuration and `examples/sample_config.json` use the canonical snake_case schema and documented commands work copy-paste.
- R8. Documentation distinguishes supported core commands and optional charts/PDF features from experimental or approximate model areas.

### Acceptance Examples

- **AE1 — Core checkout:** In an environment without reportlab, the default test command completes successfully and PDF tests are skipped with an explicit reason.
- **AE2 — PDF job:** In an environment with the PDF extra installed, PDF tests execute and pass rather than being silently skipped.
- **AE3 — Fresh install:** In a clean virtual environment, installing the package and running `mantissa --version`, `mantissa validate --config examples/sample_config.json`, and one small projection succeeds.
- **AE4 — Documentation:** A user copying the README minimal JSON can run validation without unknown-key warnings or missing required-field errors.

### Success Criteria

- Required CI status is green on the default branch.
- Core test run has no collection errors and no dependency-related skips except intentionally optional tests.
- Optional PDF job proves PDF generation independently.
- No runtime import used by the core engine is absent from package metadata.
- One version value drives package and CLI reporting.

### Scope Boundaries

**In scope:** dependency metadata, optional-test isolation, version metadata, CI, install smoke testing, README/sample schema alignment, release-surface documentation.

**Deferred for later:** survivor lifecycle, monetary-convention wiring, reproducibility metadata, tax/cash-flow fixture expansion, historical-data provenance, annual/monthly engine unification.

**Outside this slice:** new retirement-planning behavior and broad refactors unrelated to release readiness.

## Planning Contract

### Key Technical Decisions

- **KTD1 — Keep PDF optional:** Gate the PDF test module on reportlab availability; run it unskipped in a dedicated CI job with the PDF extra. This preserves lightweight core installation while making PDF support verifiable.
- **KTD2 — Declare NumPy as core:** Add NumPy to runtime dependencies because `engine.py` and `simulators.py` import it unconditionally. Do not make core simulation depend on an optional extra.
- **KTD3 — Use one package version source:** Make package metadata derive from the package version declaration and remove independent CLI/package literals. Align the declared release with the changelog's current `0.2.0`; update the changelog only if implementation finds that entry is not the intended release line.
- **KTD4 — CI tests installed artifacts:** Add a test extra containing pytest and the Python 3.9 `tomli` compatibility dependency. Keep normal tests against an editable install for speed, and add a clean environment smoke step that installs the built wheel/sdist to catch packaging omissions.
- **KTD5 — Treat sample config as canonical:** Update every README configuration example and field table to the validator's snake_case keys and parser-supported enum values, including `pre_tax`. Test both validation and projection of the documented configuration. Do not add a compatibility translation layer in this release-foundation slice.

### High-Level Technical Design

The release path has four gates: package metadata and dependency declaration; core test collection and execution; optional-feature verification; and documentation/install smoke verification. CI should expose core and optional gates separately so an unavailable optional feature cannot hide a core regression, while optional-feature failure remains visible to maintainers.

### Assumptions

- Python support remains `>=3.9` and current classifiers remain authoritative; test tooling must support Python 3.9.
- PDF and chart extras stay optional.
- Existing test behavior is the compatibility baseline; this slice should not alter financial calculations.
- The changelog's `0.2.0` entry represents the intended current release line.

### Sequencing

1. Fix dependency and version contracts with focused tests.
2. Isolate optional PDF tests and verify the complete default suite.
3. Add CI core, optional-PDF, and clean-install smoke gates.
4. Canonicalize README/sample configuration and document supported versus experimental surface.
5. Run the full verification contract and review the final diff for scope creep.

## Implementation Units

### U1. Runtime dependency and version contract

- **Goal:** Make installation metadata and reported version consistent.
- **Requirements:** R3, R4.
- **Files:** `pyproject.toml`, `src/retirement_planner/__init__.py`, `src/retirement_planner/cli.py`, `tests/cli/test_optional_deps.py`, `tests/cli/test_cli_contracts.py`.
- **Approach:** Add NumPy to core dependencies and doctor reporting, and add a test extra with pytest plus `tomli` for Python <3.11. Select one version source compatible with Hatchling, expose it through the package, and have CLI version output use that source. Align the declared version with the current changelog release.
- **Test scenarios:** Core dependency metadata contains NumPy; doctor lists NumPy as core; package and CLI report the same version; installed metadata agrees with package version; the newest changelog heading matches the package version; test collection works on Python 3.9.
- **Verification:** Targeted dependency/version tests, then the full default suite.

### U2. Optional PDF test isolation

- **Goal:** Restore a green default test command while retaining complete PDF coverage.
- **Requirements:** R1, R2.
- **Files:** `tests/cli/test_pdf_report.py`, `tests/cli/test_optional_deps.py`, `pyproject.toml` if pytest markers/configuration are needed.
- **Approach:** Skip the PDF module at collection when reportlab is unavailable with an explicit dependency reason. Keep PDF extra declaration and ensure tests execute normally when reportlab is installed.
- **Test scenarios:** No-reportlab collection succeeds and reports an intentional skip; reportlab-installed run creates valid PDF output and exercises all existing PDF tests; core CLI remains usable without reportlab.
- **Verification:** `python -m pytest -q`; a PDF-extra test invocation.

### U3. CI and clean-install smoke gate

- **Goal:** Make release readiness repeatable on every change.
- **Requirements:** R5, R6.
- **Files:** `.github/workflows/ci.yml`, `pyproject.toml`, and a new `tests/regression/test_readme_config.py` if a reusable documentation-config test is needed.
- **Approach:** Add a core CI job across the supported Python versions using the test extra, a PDF-extra job, and an isolated package-install smoke step. Build the distribution, install it into a fresh environment, run the installed `mantissa` console script with a config generated by `mantissa init`, and fail on packaging omissions. Keep source-tree README/sample validation separate from the installed-artifact smoke so the wheel is not assumed to contain `examples/`.
- **Test scenarios:** Core matrix installs the test extra and runs tests; PDF job installs `.[test,pdf]` and runs PDF tests; clean environment runs `mantissa --version`, `mantissa init`, `mantissa validate`, and a small projection; README config test executes validation and projection; workflow fails when a declared runtime dependency is removed.
- **Verification:** Local reproduction of each CI command plus a workflow syntax check where available.

### U4. Canonical documentation and release surface

- **Goal:** Ensure first-run documentation matches actual parser behavior and communicates support boundaries.
- **Requirements:** R7, R8.
- **Files:** `README.md`, `examples/sample_config.json`, `tests/regression/test_readme_config.py`, possibly `CHANGELOG.md` for release-foundation notes.
- **Approach:** Replace camelCase keys and parser-sensitive enum values in every README configuration example and field table, verify documented commands against the installed CLI, link users to the fuller sample, and label optional/approximate/experimental areas without implying unsupported precision. The regression test should extract the README JSON block rather than maintain a second hand-copied fixture.
- **Test scenarios:** README JSON validates and produces a projection; sample config validates; documented core commands have successful smoke coverage; optional charts/PDF installation instructions match extras.
- **Verification:** Parse and validate the documented config, run the documented minimal commands, inspect README for stale key names and unsupported claims.

## Verification Contract

| Gate | Command or evidence | Applies to |
|---|---|---|
| Default suite | `python -m pytest -q` | Every change; must pass without PDF installed |
| PDF suite | `python -m pip install -e '.[test,pdf]' && python -m pytest -q tests/cli/test_pdf_report.py` | Optional PDF job |
| Targeted contract tests | `python -m pytest -q tests/cli/test_optional_deps.py tests/cli/test_cli_contracts.py` | U1/U2 |
| Config smoke | Installed `mantissa validate --config ...` followed by a minimal `mantissa project --config ... --format json` | U3/U4 |
| Clean install | Build package, install into fresh virtual environment, run `mantissa --version`, `mantissa init`, then validation and projection against the generated config | U3 |
| Diff hygiene | `git diff --check` and final `git status --short` | Before completion |

The required release gate is the default suite plus clean-install smoke. PDF is a separate required optional-feature gate, not a prerequisite for core installation.

## Definition of Done

- U1–U4 changes are implemented without unrelated model behavior changes.
- `python -m pytest -q` passes in an environment without reportlab.
- PDF tests pass when the PDF extra is installed.
- CI workflow contains separate core, PDF, and clean-install coverage.
- Clean installation runs the documented CLI path successfully.
- Package, CLI, and newest changelog version are consistent.
- README configuration uses canonical schema keys and enum values, validates, and produces a projection.
- Supported, optional, approximate, and deferred capabilities are clearly labeled.
- `git diff --check` passes, abandoned experimental edits are removed, and final tree contains only intentional changes.
