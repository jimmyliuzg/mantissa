"""Optimizer feasibility regression tests."""
from retirement_planner.optimizer import (
    FeasibilityResult, YearDecision, WithdrawalOptimizer,
)


def accounts():
    return {
        "ira": {"balance": 100_000, "type": "trad_ira", "tax_treatment": "pre_tax"},
        "brokerage": {"balance": 50_000, "type": "brokerage", "tax_treatment": "taxable"},
    }


def test_feasibility_accepts_cash_balance_and_rmd_constraints():
    decision = YearDecision(
        taxable_withdrawals={"brokerage": 10_000},
        pretax_withdrawals={"ira": 20_000},
        spending_target=30_000,
    )
    result = WithdrawalOptimizer().evaluate_feasibility(
        decision, accounts(), spending_target=30_000, rmd_required=20_000,
    )
    assert isinstance(result, FeasibilityResult)
    assert result.feasible
    assert result.violations == []


def test_feasibility_reports_cash_shortfall():
    result = WithdrawalOptimizer().evaluate_feasibility(
        YearDecision(roth_withdrawals={"ira": 1_000}),
        accounts(), spending_target=2_000,
    )
    assert not result.feasible
    assert result.cash_shortfall == 1_000
    assert any("cash shortfall" in reason for reason in result.rejection_reasons)


def test_feasibility_reports_balance_and_rmd_violations():
    result = WithdrawalOptimizer().evaluate_feasibility(
        YearDecision(pretax_withdrawals={"ira": 120_000}),
        accounts(), spending_target=120_000, rmd_required=125_000,
    )
    assert not result.feasible
    assert result.rmd_shortfall == 5_000
    assert any("exceeds balance" in reason for reason in result.violations)
    assert any("RMD shortfall" in reason for reason in result.violations)


def test_generated_baseline_covers_spending_when_assets_allow():
    candidates = WithdrawalOptimizer().generate_candidates(
        2036, 66, accounts(), 30_000, 20_000, 100_000, 0,
    )
    baseline = next(c for c in candidates if c.label == "rmd_only")
    result = WithdrawalOptimizer().evaluate_feasibility(
        baseline.decision, accounts(), 30_000, 20_000,
    )
    baseline.feasibility = result
    assert result.feasible
    assert baseline.decision.total_cash_in == 30_000
