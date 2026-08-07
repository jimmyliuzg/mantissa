"""Tests for enhancement modules: SS optimizer and Roth conversion optimizer."""
from datetime import date

import pytest

from retirement_planner.engine import RetirementPlanner
from retirement_planner.enhancements import (
    RothConversionOptimizer,
    SocialSecurityOptimizer,
)
from retirement_planner.models import (
    Account, EconomicAssumptions, Expense, Person, Scenario, SocialSecurity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_planner(accounts=None, expenses=None, ss=None) -> RetirementPlanner:
    person_kwargs = dict(
        birth_date=date(1970, 1, 1),
        retirement_date=date(2030, 1, 1),
        longevity_age=90,
    )
    scenario = Scenario(
        name="Enhancement Test",
        description="",
        primary=Person(name="Primary", **person_kwargs),
        spouse=Person(name="Spouse", **person_kwargs),
        economic=EconomicAssumptions(),
        accounts=accounts or [],
        income_streams=[],
        expenses=expenses or [],
        mortgages=[],
        social_security=ss or SocialSecurity(
            primary_benefit_at_67=3000,
            spouse_benefit_at_67=2500,
        ),
        state="CA",
    )
    return RetirementPlanner(scenario)


@pytest.fixture
def planner():
    return _make_planner()


# ---------------------------------------------------------------------------
# SocialSecurityOptimizer.calculate_benefit_at_age
# ---------------------------------------------------------------------------
def test_ss_benefit_at_67_is_full(planner):
    opt = SocialSecurityOptimizer(planner)
    assert opt.calculate_benefit_at_age(planner.scenario.primary, 67) == 3000


def test_ss_benefit_at_62_is_reduced(planner):
    """Age 62: 5 years early → 3×6.67% + 2×5% = 30.01% reduction.

    3,000 × (1 - 0.3001) = 2,099.70
    """
    opt = SocialSecurityOptimizer(planner)
    benefit = opt.calculate_benefit_at_age(planner.scenario.primary, 62)
    assert benefit == pytest.approx(2_099.70, abs=0.01)


def test_ss_benefit_at_70_is_increased(planner):
    """Age 70: 3 years late → 3×8% = 24% credit → 3,000 × 1.24 = 3,720."""
    opt = SocialSecurityOptimizer(planner)
    benefit = opt.calculate_benefit_at_age(planner.scenario.primary, 70)
    assert benefit == pytest.approx(3_720.00, abs=0.01)


def test_ss_benefit_spouse_uses_spouse_amount(planner):
    opt = SocialSecurityOptimizer(planner)
    assert opt.calculate_benefit_at_age(planner.scenario.spouse, 67) == 2500
    # Spouse at 62: 2,500 × 0.6999 = 1,749.75
    benefit = opt.calculate_benefit_at_age(planner.scenario.spouse, 62)
    assert benefit == pytest.approx(1_749.75, abs=0.01)


def test_ss_benefit_monotonic_in_claiming_age(planner):
    opt = SocialSecurityOptimizer(planner)
    benefits = [
        opt.calculate_benefit_at_age(planner.scenario.primary, age)
        for age in (62, 64, 67, 68, 70)
    ]
    assert benefits == sorted(benefits)


# ---------------------------------------------------------------------------
# SocialSecurityOptimizer.compare_strategies
# ---------------------------------------------------------------------------
def test_compare_strategies_finds_optimal(planner):
    opt = SocialSecurityOptimizer(planner)
    result = opt.compare_strategies()

    assert "strategies" in result
    assert "optimal" in result
    assert len(result["strategies"]) == 36  # 6 primary × 6 spouse ages

    optimal = result["optimal"]
    # Optimal must beat or tie every other strategy
    for s in result["strategies"].values():
        assert optimal["total_lifetime"] >= s["total_lifetime"]


def test_compare_strategies_optimal_is_delay_to_70(planner):
    """With fixed longevity of 90, delaying to 70 maximizes lifetime benefits."""
    opt = SocialSecurityOptimizer(planner)
    optimal = opt.compare_strategies()["optimal"]
    assert optimal["primary_claiming_age"] == 70
    assert optimal["spouse_claiming_age"] == 70


def test_compare_strategies_strategy_fields(planner):
    opt = SocialSecurityOptimizer(planner)
    s = opt.compare_strategies()["strategies"]["primary_67_spouse_67"]
    assert s["primary_monthly"] == 3000
    assert s["spouse_monthly"] == 2500
    assert s["primary_lifetime"] == 3000 * 12 * (90 - 67)
    assert s["total_lifetime"] == s["primary_lifetime"] + s["spouse_lifetime"]


# ---------------------------------------------------------------------------
# RothConversionOptimizer.find_optimal_conversions
# ---------------------------------------------------------------------------
def _ira_accounts():
    return [
        Account(id="trad_ira", name="Traditional IRA", account_type="trad_ira",
                tax_treatment="pre_tax", balance=500_000),
        Account(id="roth_ira", name="Roth IRA", account_type="roth_ira",
                tax_treatment="roth", balance=50_000),
    ]


def test_roth_conversions_in_low_income_years():
    """No income between retirement (2030) and SS claiming (2037).

    Each year: taxable income = 0 → room in 10% bracket = $23,200.
    Expect 8 conversions (2030..2037 inclusive) of $23,200 each at 10%.
    """
    planner = _make_planner(accounts=_ira_accounts())
    opt = RothConversionOptimizer(planner)
    conversions = opt.find_optimal_conversions()

    assert len(conversions) == 8
    years = [c.year for c in conversions]
    assert years == list(range(2030, 2038))
    for c in conversions:
        assert c.source_account == "trad_ira"
        assert c.target_account == "roth_ira"
        assert c.amount == pytest.approx(23_200.0)
        assert c.tax_bracket == 0.10
        assert c.tax_cost == pytest.approx(2_320.0)


def test_roth_conversions_respect_max_annual_amount():
    planner = _make_planner(accounts=_ira_accounts())
    opt = RothConversionOptimizer(planner)
    conversions = opt.find_optimal_conversions(max_annual_amount=10_000)

    assert len(conversions) > 0
    for c in conversions:
        assert c.amount <= 10_000


def test_roth_conversions_empty_without_ira_accounts():
    """No trad_ira / roth_ira pair → no conversions possible."""
    planner = _make_planner(accounts=[
        Account(id="401k", name="401k", account_type="401k",
                tax_treatment="pre_tax", balance=500_000),
    ])
    opt = RothConversionOptimizer(planner)
    assert opt.find_optimal_conversions() == []


def test_roth_conversions_empty_without_roth_account():
    planner = _make_planner(accounts=[
        Account(id="trad_ira", name="Traditional IRA", account_type="trad_ira",
                tax_treatment="pre_tax", balance=500_000),
    ])
    opt = RothConversionOptimizer(planner)
    assert opt.find_optimal_conversions() == []


def test_conversion_benefit_summary():
    planner = _make_planner(accounts=_ira_accounts())
    opt = RothConversionOptimizer(planner)
    conversions = opt.find_optimal_conversions()
    benefit = opt.calculate_conversion_benefit(conversions)

    total = sum(c.amount for c in conversions)
    assert benefit["total_converted"] == pytest.approx(total)
    assert benefit["num_conversion_years"] == len(conversions)
    assert benefit["total_tax_cost"] == pytest.approx(
        sum(c.tax_cost for c in conversions))
    # Future tax assumed at 32% — savings positive when converting at 10%
    assert benefit["estimated_future_tax"] == pytest.approx(total * 0.32)
    assert benefit["tax_savings"] > 0
