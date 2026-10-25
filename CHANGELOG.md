# Changelog

## Unreleased — optional refinements and goal outcomes

- Separate planned/adjusted spending coverage, account access and after-estate legacy outcomes; expose first funding gaps and consistent browser/CLI/report definitions while retaining compatibility success.
- Replace categorical result advice with goal-specific rates and add labeled terminal estate estimates for single-household/stochastic legacy diagnostics.
- Preserve the short wizard path while adding optional account breakdown, statement date, basis, Roth principal, investment-income profiles and spending flexibility.
- Resolve assumptions in Python once and expose provided/estimated/missing readiness; total-only account access stays unassessed.
- Correct canonical wizard/editor return and Social Security fields, annual start dates and explicit initial legacy goal.
- Model taxable interest, qualified/nonqualified dividends, long-term fund distributions and reinvestment basis within total return; feed taxes, NIIT and healthcare income.
- Apply spending strategies to actual expense IDs before funding and deductions; report cut frequency, years and depth.
- Deliver priority 4 goal outcomes; keep native equity cohorts scoped as upcoming priority 5.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- Default withdrawal feasibility to conservative penalty-free access, with declared Roth IRA principal and conversion clocks; expose access failures separately from portfolio depletion.
- Keep nominal tax basis and mortgage contracts consistent across real/nominal output, including housing transactions, RMD references and healthcare tax units.
- Align the first nominal projection row with the base-year price index used for its cash flows.

### Added
- Anonymous access/accounting regressions and a privacy content guard in CI.

## [0.2.0] - 2026-07-22

### Added
- CLI interface with `run`, `report`, `compare`, `sensitivity` commands
- Report generation module (JSON, CSV, Markdown export)
- Visualization module (net worth trajectory, MC fan chart, income vs expenses, tax breakdown)
- Sensitivity analysis module (tests single variable impact on success rate)
- Entry point: `mantissa` command via `pyproject.toml`

## [0.1.0] - 2026-07-06

### Added
- Core retirement planning engine with year-by-year cash flow projection
- Account growth modeling for multiple account types (401k, Roth IRA, brokerage, HSA, etc.)
- Federal + California state tax calculations with bracket-based computation
- Social Security benefit modeling with COLA adjustments
- Monte Carlo simulation for success rate estimation
- Scenario comparison across multiple retirement strategies
- Roth conversion planning support
- JSON-based configuration for easy plan setup
- Sample configuration with documented examples
