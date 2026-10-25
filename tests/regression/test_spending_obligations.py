"""Spending responses cannot invent savings from non-reducible obligations."""
from datetime import date

import pytest

from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import (
    Account, AgeEvent, EconomicAssumptions, Expense, MonetaryConvention,
    Mortgage, Person, Scenario,
)


def make_planner(strategy="dynamic", **kwargs):
    return RetirementPlanner(Scenario(
        name="Spending obligations", description="", start_year=2026,
        primary=Person("A", date(1990, 1, 1), date(2026, 1, 1), 38,
                       coverage_type="none"), spouse=None,
        economic=EconomicAssumptions(general_inflation=0.025),
        accounts=kwargs.pop("accounts", [Account(
            "cash", "Cash", "checking", "taxable", 100_000,
            asset_class="cash", growth_rate=0)]),
        income_streams=[], expenses=kwargs.pop("expenses", []),
        mortgages=kwargs.pop("mortgages", []),
        withdrawal_strategy=strategy, **kwargs))


def expense(id, monthly=1000, **kwargs):
    return Expense(id, id, monthly, date(2026, 1, 1), date(2030, 1, 1), **kwargs)


@pytest.mark.parametrize("strategy", ["dynamic", "guardrails", "percent_of_portfolio", "floor_ceiling"])
def test_mortgage_and_one_time_obligations_survive_a_portfolio_crash(strategy):
    p = make_planner(strategy, expenses=[
        expense("basic", 1000),
        expense("repair", 0, is_one_time=True, one_time_amount=20_000,
                one_time_date=date(2026, 7, 1)),
    ], mortgages=[Mortgage("m", "Loan", "home", 100_000, 0, 2000,
                           date(2026, 1, 1), date(2030, 1, 1))])
    p._starting_portfolio = 100_000
    data = p.calculate_annual_expenses(2026)
    assert p.apply_withdrawal_strategy(2026, 56_000, 1, 100_000, data) == pytest.approx(56_000)
    row = p.project_cash_flow()[0]
    assert row["expenses"] == pytest.approx(56_000)


def test_age_event_and_real_growth_are_protected():
    p = make_planner(expenses=[expense("healthcare", 1000, real_growth_rate=.1)],
                     age_events=[AgeEvent(36, "healthcare", 2000)])
    # The previous floor used the original 1000/month, ignoring both overrides.
    year = 2027
    data = p.calculate_annual_expenses(year)
    assert data["total"] == pytest.approx(26_400)
    assert p.apply_dynamic_spending(year, data["total"], 1, data) == pytest.approx(26_400)


def test_reduction_never_exceeds_the_category_limit():
    p = make_planner(expenses=[expense("basic", 9000),
                              expense("trips", 1000, is_must_spend=False, min_reduction=.25)])
    row = p.project_cash_flow()[0]
    assert row["expenses"] == pytest.approx(117_000)  # only 3k may be cut


def test_stress_and_dynamic_do_not_cut_the_same_allowance_twice():
    p = make_planner(expenses=[expense("basic", 9000),
                              expense("trips", 1000, is_must_spend=False, min_reduction=.5)])
    for stress in (0, .5, 1):
        assert p.project_cash_flow(stress_level=stress)[0]["expenses"] == pytest.approx(114_000)


def test_nominal_floor_preserves_inflated_obligations():
    p = make_planner(monetary_convention=MonetaryConvention.NOMINAL,
                     expenses=[expense("basic", 1000)])
    row = p.project_cash_flow()[1]
    assert row["expenses"] == pytest.approx(12_000 * 1.025)


def test_paid_off_mortgage_does_not_leave_a_phantom_floor():
    p = make_planner(expenses=[expense("basic", 1000)], mortgages=[
        Mortgage("m", "Loan", "home", 12_000, 0, 1000,
                 date(2026, 1, 1), date(2030, 1, 1))])
    rows = p.project_cash_flow()
    assert rows[0]["expenses"] == pytest.approx(24_000)
    assert rows[1]["expenses"] == pytest.approx(12_000)


def test_flexible_funded_expenses_are_cut_before_payment():
    p = make_planner(expenses=[expense("basic", 1000),
                              expense("giving", 1000, is_must_spend=False,
                                      min_reduction=1, funding_account="cash")])
    row = p.project_cash_flow()[0]
    assert row["funded_expenses"] == pytest.approx(9_600)
    assert row["cash_expenses"] == pytest.approx(12_000)
    assert row["expenses"] == pytest.approx(21_600)
    assert row["expenses_by_id"]["giving"] == pytest.approx(9_600)


def test_medical_excess_inflation_is_not_cut():
    health = expense("health", 1000, category="medical")
    fixed = make_planner("fixed", expenses=[health]).project_cash_flow()
    dynamic = make_planner("dynamic", expenses=[health]).project_cash_flow()
    assert fixed[1]["expenses"] > 12_000
    assert dynamic[1]["expenses"] == pytest.approx(fixed[1]["expenses"])
