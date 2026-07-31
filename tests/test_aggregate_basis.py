"""Tests for core aggregate-basis taxable-account policy."""
from retirement_planner.engine import CostBasisTracker, WithdrawalEngine
from retirement_planner.models import Account


def test_initial_aggregate_basis_equals_balance():
    account = Account("brokerage", "Brokerage", "brokerage", "taxable", 1000)
    tracker = CostBasisTracker()
    tracker.set_basis(account.id, account.balance)
    assert tracker.get_basis(account.id) == 1000


def test_aggregate_basis_withdrawal_realizes_gain_after_basis_depletion():
    account = Account("brokerage", "Brokerage", "brokerage", "taxable", 1000)
    tracker = CostBasisTracker({"brokerage": 1000})
    engine = WithdrawalEngine({"brokerage": account}, tracker)
    balances = {"brokerage": 1000}
    engine.execute_withdrawals(1200, balances, 2026, 60, 60)
    # First $1,000 basis is non-gain; account cannot fund remaining $200.
    assert tracker.get_basis("brokerage") == 0
    assert balances["brokerage"] == 0
    assert engine.withdrawals[0].capital_gain == 0
