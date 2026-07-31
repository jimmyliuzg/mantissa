"""Multi-year monetary and tax convention regression tests."""
from datetime import date

import pytest

from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import (
    Account, EconomicAssumptions, MonetaryConvention, Person, Scenario,
)
from retirement_planner.monetary import MonetaryPolicy


def planner_for(convention, balance=100.0, growth=0.08):
    primary = Person("Primary", date(1970, 1, 1), date(2040, 1, 1), 90)
    spouse = Person("Spouse", date(1970, 1, 1), date(2040, 1, 1), 90)
    scenario = Scenario(
        name="monetary regression", description="", primary=primary,
        spouse=spouse, economic=EconomicAssumptions(general_inflation=0.025),
        accounts=[Account("portfolio", "Portfolio", "brokerage", "taxable",
                          balance, growth_rate=growth)],
        income_streams=[], expenses=[], mortgages=[],
        monetary_convention=convention, legacy_goal=0,
    )
    return RetirementPlanner(scenario)


def test_real_multi_year_return_stays_real():
    planner = planner_for(MonetaryConvention.REAL)
    assert planner.get_account_balance("portfolio", planner.start_year + 2) == pytest.approx(
        100.0 * 1.08 ** 2
    )


def test_nominal_multi_year_return_compounds_inflation():
    planner = planner_for(MonetaryConvention.NOMINAL)
    nominal_return = 1.08 * 1.025 - 1
    assert planner.get_account_balance("portfolio", planner.start_year + 2) == pytest.approx(
        100.0 * (1 + nominal_return) ** 2
    )


def test_tax_conversion_round_trip_preserves_value():
    for convention in (MonetaryConvention.REAL, MonetaryConvention.NOMINAL):
        policy = MonetaryPolicy(convention, base_year=2026, inflation=0.025)
        value = 50_000.0
        nominal = policy.to_nominal_for_tax(value, 2036)
        restored = policy.from_nominal_after_tax(nominal, 2036)
        assert restored == pytest.approx(value)


def test_tax_base_year_is_unchanged_in_both_conventions():
    for convention in (MonetaryConvention.REAL, MonetaryConvention.NOMINAL):
        policy = MonetaryPolicy(convention, base_year=2026, inflation=0.025)
        assert policy.to_nominal_for_tax(12_345, 2026) == pytest.approx(12_345)
        assert policy.from_nominal_after_tax(12_345, 2026) == pytest.approx(12_345)


def test_real_and_nominal_simulations_produce_valid_multi_year_tax_results():
    real = planner_for(MonetaryConvention.REAL, balance=500_000)
    nominal = planner_for(MonetaryConvention.NOMINAL, balance=500_000)
    real_result = real.run_single_simulation(return_volatility=0)
    nominal_result = nominal.run_single_simulation(return_volatility=0)
    assert real_result["lifetime_taxes"] >= 0
    assert nominal_result["lifetime_taxes"] >= 0
    assert real_result["final_net_worth"] != nominal_result["final_net_worth"]


def test_projection_rows_have_consistent_monetary_fields():
    rows = planner_for(MonetaryConvention.REAL).project_cash_flow()
    assert rows
    required = {"year", "income", "expenses", "taxes", "net_worth"}
    assert required.issubset(rows[0])
    assert all(row["year"] < rows[index + 1]["year"]
               for index, row in enumerate(rows[:-1]))
    assert all(row["taxes"] >= 0 for row in rows)
