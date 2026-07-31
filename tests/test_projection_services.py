"""Tests for the shared projection context/state boundary."""
from retirement_planner.projection.services import make_state, make_year_context


def test_year_context_is_shared_by_projection_paths():
    context = make_year_context(2040, 2026, 1970, 1972)
    assert context.primary_age == 70
    assert context.spouse_age == 68
    assert context.younger_age == 68
    assert context.years_from_base == 14


def test_make_state_shares_legacy_balance_mapping():
    balances = {"brokerage": 100.0}
    state = make_state(make_year_context(2026, 2026, 1970, 1972), balances)
    state.balances["brokerage"] = 125.0
    assert balances["brokerage"] == 125.0
    state.add_warning("simplified deterministic tax")
    assert state.as_dict()["warnings"] == ["simplified deterministic tax"]
