"""Regression tests for the audit-driven engine hardening work."""
from datetime import date

import pytest

from retirement_planner.engine import RetirementPlanner, WithdrawalEngine, CostBasisTracker
from retirement_planner.models import (
    Account, AssetAllocation, EconomicAssumptions, GlidepathConfig,
    MonetaryConvention, Person, Scenario,
)
from retirement_planner.simulators import MonteCarloEngine
from retirement_planner.tax_lots import TaxLotTracker


def make_people(primary_birth=1950, spouse_birth=1960):
    return (
        Person("Primary", date(primary_birth, 1, 1), date(2030, 1, 1), 95),
        Person("Spouse", date(spouse_birth, 1, 1), date(2030, 1, 1), 95),
    )


def make_planner(accounts=None, convention=MonetaryConvention.REAL, glidepath=None):
    primary, spouse = make_people()
    scenario = Scenario(
        name="audit", description="", primary=primary, spouse=spouse,
        economic=EconomicAssumptions(general_inflation=0.025),
        accounts=accounts or [], income_streams=[], expenses=[], mortgages=[],
        monetary_convention=convention, glidepath=glidepath,
    )
    return RetirementPlanner(scenario)


def test_rmd_uses_account_owner_age_and_reinvests_surplus():
    accounts = [
        Account("p_ira", "Primary IRA", "trad_ira", "pre_tax", 265_000, owner="primary"),
        Account("s_ira", "Spouse IRA", "trad_ira", "pre_tax", 265_000, owner="spouse"),
        Account("cash", "Cash", "checking", "taxable", 0, growth_rate=0),
    ]
    planner = make_planner(accounts)
    engine = WithdrawalEngine(planner.accounts, CostBasisTracker())
    balances = {a.id: a.balance for a in accounts}

    # Primary is 76 and spouse is 66. Only primary's IRA has an RMD.
    withdrawals = engine.execute_withdrawals(
        needed=1_000, balances=balances, year=2026,
        primary_age=76, spouse_age=66, sale_date=date(2026, 12, 31),
    )

    primary_rmd = next(w for w in withdrawals if w.account_id == "p_ira")
    assert primary_rmd.amount == pytest.approx(265_000 / 23.7)
    assert not any(w.account_id == "s_ira" for w in withdrawals)
    reinvested = next(w for w in withdrawals if w.tax_treatment == "rmd_reinvested")
    assert balances["cash"] == pytest.approx(reinvested.amount)
    assert reinvested.amount == pytest.approx(primary_rmd.amount - 1_000)


def test_ira_rmds_are_aggregated_by_owner():
    accounts = [
        Account("ira1", "IRA 1", "trad_ira", "pre_tax", 100_000, owner="primary"),
        Account("ira2", "IRA 2", "trad_ira", "pre_tax", 200_000, owner="primary"),
    ]
    planner = make_planner(accounts)
    engine = WithdrawalEngine(planner.accounts, CostBasisTracker())
    balances = {a.id: a.balance for a in accounts}
    withdrawals = engine.execute_withdrawals(0, balances, 2026, 76, 76)
    rmds = [w for w in withdrawals if w.tax_treatment == "ordinary"]
    assert sum(w.amount for w in rmds) == pytest.approx(300_000 / 23.7)
    assert rmds[0].amount / rmds[1].amount == pytest.approx(0.5)


def test_real_and_nominal_allocation_returns_are_distinct_and_consistent():
    account = Account("a", "Portfolio", "brokerage", "taxable", 100_000, growth_rate=0.08)
    alloc = AssetAllocation(0.5, 0.5)
    real = make_planner([account], MonetaryConvention.REAL)
    nominal = make_planner([account], MonetaryConvention.NOMINAL)
    # equity_rate=0.08 (from account.growth_rate), bond_rate=0.025 (scenario default)
    # 0.5 * 0.08 + 0.5 * 0.025 = 0.0525
    assert real.get_growth_rate_for_allocation(account, alloc) == pytest.approx(0.0525)
    expected_nominal = 0.5 * ((1.08 * 1.025) - 1) + 0.5 * ((1.025 * 1.025) - 1)
    assert nominal.get_growth_rate_for_allocation(account, alloc) == pytest.approx(expected_nominal)


def test_deterministic_projection_uses_account_allocation_override():
    account = Account("a", "Bonds", "brokerage", "taxable", 100_000,
                      growth_rate=0.08, equity_pct=0.0, expense_ratio=0.001)
    planner = make_planner([account])
    # equity_pct=0.0 → 100% bonds. bond_rate=0.025 (scenario default).
    # account.growth_rate=0.08 used as equity_rate, but allocation is 0% equity.
    expected_rate = 0.025 - 0.001
    assert planner.get_account_balance("a", planner.start_year + 1) == pytest.approx(
        100_000 * (1 + expected_rate)
    )


def test_glidepath_validates_anchor_and_tent_values():
    with pytest.raises(ValueError):
        GlidepathConfig(equity_by_age={60: 1.2})
    with pytest.raises(ValueError):
        GlidepathConfig(equity_by_age={60: 0.5}, tent_ramp_years=-1)


def test_tax_lot_partial_liquidation_is_explicit():
    tracker = TaxLotTracker()
    tracker.add_purchase("brokerage", 10, 50, date(2020, 1, 1))
    result = tracker.liquidate_with_price(
        "brokerage", 15, 60, sale_date=date(2026, 1, 1)
    )
    assert result.total_shares == 10
    assert result.requested_shares == 15
    assert result.unfilled_shares == 5


def test_monte_carlo_seed_reproduces_results():
    planner = make_planner([
        Account("a", "Portfolio", "brokerage", "taxable", 500_000),
    ])
    mc = MonteCarloEngine(planner)
    first = mc.run(num_simulations=5, seed=123)
    second = mc.run(num_simulations=5, seed=123)
    assert first == second
