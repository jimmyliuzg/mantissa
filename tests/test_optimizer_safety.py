"""Safety-status tests for experimental optimizer recommendations."""
from retirement_planner.optimizer import (
    DecisionTrace, OptimizerConfig, WithdrawalOptimizer,
)


def test_optimizer_is_experimental_by_default():
    optimizer = WithdrawalOptimizer()
    assert optimizer.status == "experimental"


def test_optimizer_trace_discloses_experimental_status():
    optimizer = WithdrawalOptimizer()
    _, trace = optimizer.optimize_year(
        year=2036, age=66,
        accounts={"ira": {"balance": 100_000, "type": "trad_ira", "tax_treatment": "pre_tax"}},
        spending_target=20_000, rmd_required=0,
        bracket_top=100_000, ordinary_income=0,
    )
    assert any("experimental" in reason.lower() for reason in trace.reasons)


def test_optimizer_can_explicitly_report_production_status():
    assert WithdrawalOptimizer(OptimizerConfig(experimental=False)).status == "production"
