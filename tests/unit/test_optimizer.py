"""Tests for optimizer.py — withdrawal/Roth conversion optimizer."""
import pytest
from retirement_planner.optimizer import (
    YearDecision, CandidateDecision, DecisionTrace,
    WithdrawalOptimizer, OptimizerConfig,
    FixedSpendingPolicy, GuardrailsPolicy, VPWPolicy, FloorCeilingPolicy,
)


# ---------------------------------------------------------------------------
# YearDecision
# ---------------------------------------------------------------------------
class TestYearDecision:

    def test_empty_decision(self):
        d = YearDecision()
        d.compute_totals()
        assert d.total_cash_in == 0
        assert d.total_ordinary_income == 0

    def test_withdrawals_compute_totals(self):
        d = YearDecision(
            taxable_withdrawals={"brokerage": 50_000},
            pretax_withdrawals={"401k": 30_000},
            roth_withdrawals={"roth": 10_000},
        )
        d.compute_totals()
        assert d.total_cash_in == 90_000
        assert d.total_ordinary_income == 30_000

    def test_roth_conversion计入_ordinary(self):
        d = YearDecision(
            roth_conversions={"401k": 50_000},
        )
        d.compute_totals()
        assert d.total_ordinary_income == 50_000
        assert d.total_cash_in == 0  # conversion is not cash

    def test_realized_gains计入_taxable_event(self):
        d = YearDecision(
            realized_ltcg=20_000,
        )
        d.compute_totals()
        assert d.total_taxable_event == 20_000
        assert d.total_ordinary_income == 0


# ---------------------------------------------------------------------------
# Spending policies
# ---------------------------------------------------------------------------
class TestFixedSpendingPolicy:

    def test_returns_base(self):
        p = FixedSpendingPolicy()
        assert p.spending_target(2026, 100_000, 1_000_000, 1_100_000) == 100_000


class TestGuardrailsPolicy:

    def test_within_guardrails(self):
        p = GuardrailsPolicy()
        # Portfolio at 90% of peak → within guardrails
        assert p.spending_target(2026, 100_000, 900_000, 1_000_000) == 100_000

    def test_above_upper_guardrail(self):
        p = GuardrailsPolicy()
        # Portfolio at 130% of peak → increase
        target = p.spending_target(2026, 100_000, 1_300_000, 1_000_000)
        assert target == pytest.approx(110_000)

    def test_below_lower_guardrail(self):
        p = GuardrailsPolicy()
        # Portfolio at 70% of peak → decrease
        target = p.spending_target(2026, 100_000, 700_000, 1_000_000)
        assert target == pytest.approx(90_000)


class TestVPWPolicy:

    def test_withdrawal_rate(self):
        p = VPWPolicy(base_rate=0.04)
        target = p.spending_target(2026, 100_000, 2_000_000, 2_000_000)
        assert target == pytest.approx(80_000)

    def test_max_rate_cap(self):
        p = VPWPolicy(base_rate=0.15, max_rate=0.10)
        target = p.spending_target(2026, 100_000, 1_000_000, 1_000_000)
        assert target == pytest.approx(100_000)


class TestFloorCeilingPolicy:

    def test_healthy_portfolio(self):
        p = FloorCeilingPolicy()
        # 25x coverage → ceiling
        target = p.spending_target(2026, 100_000, 2_500_000, 2_500_000)
        assert target == pytest.approx(120_000)  # 100K * 1.20

    def test_stressed_portfolio(self):
        p = FloorCeilingPolicy()
        # 10x coverage → floor
        target = p.spending_target(2026, 100_000, 1_000_000, 1_000_000)
        assert target == pytest.approx(70_000)  # 100K * 0.70

    def test_normal_portfolio(self):
        p = FloorCeilingPolicy()
        # 20x coverage → base
        target = p.spending_target(2026, 100_000, 2_000_000, 2_000_000)
        assert target == 100_000


# ---------------------------------------------------------------------------
# Optimizer
# ---------------------------------------------------------------------------
class TestWithdrawalOptimizer:

    @pytest.fixture
    def accounts(self):
        return {
            "401k": {"balance": 500_000, "type": "401k", "tax_treatment": "pre_tax"},
            "brokerage": {"balance": 300_000, "type": "brokerage", "tax_treatment": "taxable"},
            "roth": {"balance": 100_000, "type": "roth_ira", "tax_treatment": "roth"},
        }

    def test_generate_candidates(self, accounts):
        opt = WithdrawalOptimizer()
        candidates = opt.generate_candidates(
            year=2036, age=40, accounts=accounts,
            spending_target=100_000, rmd_required=0,
            current_tax_bracket_top=201_050, ordinary_income_so_far=150_000,
        )
        assert len(candidates) >= 1
        assert all(isinstance(c, CandidateDecision) for c in candidates)

    def test_rmd_only_baseline(self, accounts):
        opt = WithdrawalOptimizer()
        candidates = opt.generate_candidates(
            year=2036, age=40, accounts=accounts,
            spending_target=100_000, rmd_required=20_000,
            current_tax_bracket_top=201_050, ordinary_income_so_far=0,
        )
        rmd_only = [c for c in candidates if c.label == "rmd_only"]
        assert len(rmd_only) == 1
        assert rmd_only[0].decision.total_ordinary_income > 0

    def test_bracket_fill_candidate(self, accounts):
        opt = WithdrawalOptimizer()
        candidates = opt.generate_candidates(
            year=2036, age=40, accounts=accounts,
            spending_target=100_000, rmd_required=0,
            current_tax_bracket_top=201_050, ordinary_income_so_far=150_000,
        )
        bracket_fills = [c for c in candidates if "bracket_fill" in c.label]
        assert len(bracket_fills) >= 1

    def test_select_best(self, accounts):
        opt = WithdrawalOptimizer()
        candidates = opt.generate_candidates(
            year=2036, age=40, accounts=accounts,
            spending_target=100_000, rmd_required=0,
            current_tax_bracket_top=201_050, ordinary_income_so_far=100_000,
        )
        best = opt.select_best(candidates, year=2036, age=40)
        assert isinstance(best, CandidateDecision)
        assert best.score < float('inf')

    def test_optimize_year(self, accounts):
        opt = WithdrawalOptimizer()
        decision, trace = opt.optimize_year(
            year=2036, age=40, accounts=accounts,
            spending_target=100_000, rmd_required=0,
            bracket_top=201_050, ordinary_income=100_000,
        )
        assert isinstance(decision, YearDecision)
        assert isinstance(trace, DecisionTrace)
        assert trace.year == 2036
        assert len(trace.reasons) > 0


# ---------------------------------------------------------------------------
# Decision trace
# ---------------------------------------------------------------------------
class TestDecisionTrace:

    def test_explain(self):
        trace = DecisionTrace(
            year=2036,
            selected=YearDecision(pretax_withdrawals={"401k": 50_000}),
            selected_label="bracket_fill_201k",
            reasons=["Fill 22% bracket", "Preserve ACA subsidy"],
            tax_cost=11_000,
            aca_subsidy=6_000,
        )
        explanation = trace.explain()
        assert "2036" in explanation
        assert "bracket_fill_201k" in explanation
        assert "$11,000" in explanation
        assert "$6,000" in explanation
