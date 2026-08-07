"""Tests for engine-backed tax evaluation in the optimizer (Phase 3.2)."""
from unittest.mock import MagicMock, patch
from retirement_planner.optimizer import (
    YearDecision, CandidateDecision, WithdrawalOptimizer, OptimizerConfig,
    TaxEvaluation, TaxEvaluator, FeasibilityResult,
)


# ---------------------------------------------------------------------------
# TaxEvaluation dataclass
# ---------------------------------------------------------------------------
def test_tax_evaluation_defaults():
    ev = TaxEvaluation()
    assert ev.total_tax == 0.0
    assert ev.aca_subsidy == 0.0
    assert ev.irmaa_cost == 0.0
    assert ev.niit == 0.0
    assert ev.total_cost == 0.0


def test_tax_evaluation_fields():
    ev = TaxEvaluation(total_tax=5000, aca_subsidy=3000, irmaa_cost=1200, niit=500)
    ev.total_cost = ev.total_tax + ev.irmaa_cost + ev.niit - ev.aca_subsidy
    assert ev.total_cost == 3700  # 5000 + 1200 + 500 - 3000


# ---------------------------------------------------------------------------
# TaxEvaluator protocol
# ---------------------------------------------------------------------------
class TestProtocolSatisfaction:
    """Verify that any callable matching the protocol passes isinstance check."""

    def test_static_evaluator_satisfies_protocol(self):
        class GoodEvaluator:
            def evaluate(self, decision, year, age, ordinary_income_baseline, family_size=2):
                return TaxEvaluation(total_tax=1000, total_cost=1000)
        assert isinstance(GoodEvaluator(), TaxEvaluator)


# ---------------------------------------------------------------------------
# Mock evaluator for unit tests (no engine dependency)
# ---------------------------------------------------------------------------
class MockTaxEvaluator:
    """Simple mock evaluator for testing optimizer integration."""

    def __init__(self, tax_per_dollar=0.22, aca_threshold=100_000, irmaa_threshold=206_000):
        self.tax_per_dollar = tax_per_dollar
        self.aca_threshold = aca_threshold
        self.irmaa_threshold = irmaa_threshold

    def evaluate(self, decision, year, age, ordinary_income_baseline, family_size=2):
        decision.compute_totals()
        additional = (
            sum(decision.pretax_withdrawals.values())
            + sum(decision.roth_conversions.values())
        )
        total_ordinary = ordinary_income_baseline + additional

        # Marginal tax estimate
        marginal_tax = additional * self.tax_per_dollar

        # ACA: subsidy only if under cliff
        aca_subsidy = 8000 if (age < 65 and total_ordinary < self.aca_threshold) else 0.0

        # IRMAA: surcharge if over threshold
        irmaa_cost = 2400 if (age >= 65 and total_ordinary > self.irmaa_threshold) else 0.0

        total_cost = marginal_tax + irmaa_cost - aca_subsidy
        return TaxEvaluation(
            total_tax=marginal_tax,
            aca_subsidy=aca_subsidy,
            irmaa_cost=irmaa_cost,
            total_cost=total_cost,
        )


# ---------------------------------------------------------------------------
# select_best with evaluator vs proxy
# ---------------------------------------------------------------------------
def _make_accounts():
    return {
        "ira": {"balance": 500_000, "type": "trad_ira", "tax_treatment": "pre_tax"},
        "brokerage": {"balance": 200_000, "type": "brokerage", "tax_treatment": "taxable"},
    }


def test_select_best_uses_evaluator_when_set():
    """When evaluator is configured, scoring uses real tax calculations."""
    config = OptimizerConfig(evaluator=MockTaxEvaluator())
    opt = WithdrawalOptimizer(config)

    candidates = [
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 50_000}, spending_target=50_000),
            label="low_withdrawal",
        ),
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 200_000}, spending_target=50_000),
            label="high_withdrawal",
        ),
    ]
    for c in candidates:
        c.decision.compute_totals()

    best = opt.select_best(
        candidates, year=2036, age=55,
        accounts=_make_accounts(), spending_target=50_000,
        ordinary_income_baseline=80_000,
    )
    # Low withdrawal should win: less tax, keeps ACA subsidy
    assert best.label == "low_withdrawal"


def test_select_best_falls_back_to_proxy_without_evaluator():
    """Without evaluator, scoring uses proxy heuristic."""
    opt = WithdrawalOptimizer()  # no evaluator

    candidates = [
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 50_000}, spending_target=50_000),
            label="low",
        ),
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 200_000}, spending_target=50_000),
            label="high",
        ),
    ]

    best = opt.select_best(
        candidates, year=2036, age=55,
        accounts=_make_accounts(), spending_target=50_000,
    )
    # Proxy scoring: lower ordinary income = lower score
    assert best.label == "low"


def test_select_best_evaluator_fallback_on_exception():
    """If evaluator raises, fall back to proxy scoring."""
    class BrokenEvaluator:
        def evaluate(self, decision, year, age, ordinary_income_baseline, family_size=2):
            raise RuntimeError("engine exploded")

    config = OptimizerConfig(evaluator=BrokenEvaluator())
    opt = WithdrawalOptimizer(config)

    candidates = [
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 50_000}, spending_target=50_000),
            label="low",
        ),
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 200_000}, spending_target=50_000),
            label="high",
        ),
    ]

    best = opt.select_best(
        candidates, year=2036, age=55,
        accounts=_make_accounts(), spending_target=50_000,
    )
    # Falls back to proxy — lower income wins
    assert best.label == "low"


# ---------------------------------------------------------------------------
# Roth conversion limit in feasibility
# ---------------------------------------------------------------------------
def test_feasibility_rejects_roth_conversion_over_limit():
    """Feasibility rejects candidates exceeding max_roth_conversion."""
    config = OptimizerConfig(max_roth_conversion=50_000)
    opt = WithdrawalOptimizer(config)

    decision = YearDecision(
        pretax_withdrawals={"ira": 30_000},
        roth_conversions={"ira": 100_000},
        spending_target=30_000,
    )
    accounts = {
        "ira": {"balance": 500_000, "type": "trad_ira", "tax_treatment": "pre_tax"},
    }
    result = opt.evaluate_feasibility(decision, accounts, spending_target=30_000)
    assert not result.feasible
    assert any("Roth conversion" in v for v in result.violations)
    assert any("exceeds limit" in v for v in result.violations)


def test_feasibility_accepts_roth_conversion_under_limit():
    """Feasibility accepts candidates within max_roth_conversion."""
    config = OptimizerConfig(max_roth_conversion=200_000)
    opt = WithdrawalOptimizer(config)

    decision = YearDecision(
        pretax_withdrawals={"ira": 30_000},
        roth_conversions={"ira": 100_000},
        spending_target=30_000,
    )
    accounts = {
        "ira": {"balance": 500_000, "type": "trad_ira", "tax_treatment": "pre_tax"},
    }
    result = opt.evaluate_feasibility(decision, accounts, spending_target=30_000)
    assert result.feasible
    assert not any("Roth" in v for v in result.violations)


# ---------------------------------------------------------------------------
# optimize_year with evaluator — trace population
# ---------------------------------------------------------------------------
def test_optimize_year_populates_trace_with_tax_evaluation():
    """optimize_year fills trace.tax_cost, aca_subsidy, irmaa_cost from evaluator."""
    config = OptimizerConfig(evaluator=MockTaxEvaluator())
    opt = WithdrawalOptimizer(config)

    decision, trace = opt.optimize_year(
        year=2036, age=55,
        accounts=_make_accounts(),
        spending_target=50_000, rmd_required=0,
        bracket_top=100_000, ordinary_income=80_000,
    )
    # Trace should have tax evaluation data populated
    assert trace.tax_cost > 0 or trace.aca_subsidy > 0  # at least one is nonzero
    # Trace reasons should include engine evaluation line
    assert any("Engine evaluation" in r for r in trace.reasons)


def test_optimize_year_no_evaluator_zeroes_trace_costs():
    """Without evaluator, trace costs stay at zero."""
    opt = WithdrawalOptimizer()  # no evaluator

    _, trace = opt.optimize_year(
        year=2036, age=55,
        accounts=_make_accounts(),
        spending_target=50_000, rmd_required=0,
        bracket_top=100_000, ordinary_income=80_000,
    )
    assert trace.tax_cost == 0.0
    assert trace.aca_subsidy == 0.0
    assert trace.irmaa_cost == 0.0


# ---------------------------------------------------------------------------
# ACA-aware candidate selection
# ---------------------------------------------------------------------------
def test_evaluator_prefers_low_income_when_aca_at_risk():
    """When ACA subsidy is at stake, evaluator should prefer lower income."""
    # Evaluator with ACA cliff at $100K
    evaluator = MockTaxEvaluator(aca_threshold=100_000, tax_per_dollar=0.22)
    config = OptimizerConfig(evaluator=evaluator)
    opt = WithdrawalOptimizer(config)

    # Baseline income $90K — adding $5K keeps ACA, adding $20K loses it
    candidates = [
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 5_000}, spending_target=5_000),
            label="aca_safe",
        ),
        CandidateDecision(
            decision=YearDecision(pretax_withdrawals={"ira": 20_000}, spending_target=5_000),
            label="aca_lose",
        ),
    ]

    best = opt.select_best(
        candidates, year=2036, age=55,
        accounts=_make_accounts(), spending_target=5_000,
        ordinary_income_baseline=90_000,
    )
    assert best.label == "aca_safe"
