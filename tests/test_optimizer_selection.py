"""Tests for feasibility-aware candidate selection."""
from retirement_planner.optimizer import CandidateDecision, YearDecision, WithdrawalOptimizer


def test_select_best_rejects_infeasible_candidate():
    optimizer = WithdrawalOptimizer()
    accounts = {"brokerage": {"balance": 1000, "type": "brokerage"}}
    bad = CandidateDecision(
        decision=YearDecision(taxable_withdrawals={"brokerage": 2000}),
        label="bad",
    )
    good = CandidateDecision(
        decision=YearDecision(taxable_withdrawals={"brokerage": 1000}),
        label="good",
    )
    selected = optimizer.select_best(
        [bad, good], 2036, 66, accounts, spending_target=1000,
    )
    assert selected.label == "good"
    assert not bad.feasibility.feasible
    assert good.feasibility.feasible


def test_optimize_trace_reports_no_feasible_candidate():
    optimizer = WithdrawalOptimizer()
    decision, trace = optimizer.optimize_year(
        2036, 66,
        {"brokerage": {"balance": 1000, "type": "brokerage"}},
        spending_target=2000, rmd_required=0,
        bracket_top=100000, ordinary_income=0,
    )
    assert trace.selected_label == "no_feasible_candidates"
    assert any("no feasible" in reason.lower() for reason in trace.reasons)
    assert decision.spending_target == 2000
    assert trace.alternatives
    assert all(candidate.feasibility is not None for candidate in trace.alternatives)
