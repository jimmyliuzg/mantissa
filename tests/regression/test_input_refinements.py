"""Fictional plans verify optional inputs against actual annual calculations."""
from copy import deepcopy
from datetime import date
import json

import pytest

from retirement_planner.config.readiness import resolve_inputs
from retirement_planner.config.validation import validate_config
from retirement_planner.engine import RetirementPlanner
from retirement_planner.investment_income import distribute
from retirement_planner.models import (Account, EconomicAssumptions, Expense,
    MonetaryConvention, Person, Scenario, SocialSecurity, TaxableIncome)
from retirement_planner.simulators import MonteCarloEngine
from retirement_planner.tax_law import FilingStatus


def config():
    return {"start_year": 2030, "primary": {"name": "Example", "birth_date": "1990-01-01", "retirement_date": "2030-01-01", "longevity_age": 42},
            "accounts": [{"id": "b", "name": "Investments", "type": "brokerage", "balance": 1_000_000}],
            "social_security": {"primary_benefit_at_67": 0, "spouse_benefit_at_67": 0}}


def planner(account=None, expenses=None, convention=MonetaryConvention.REAL, strategy="fixed", state="TX", inflation=0.025):
    return RetirementPlanner(Scenario(name="Fictional yields", description="", start_year=2030,
        primary=Person("Example", date(1990,1,1), date(2030,1,1), 42, coverage_type="none"), spouse=None,
        accounts=[account or Account("b","Investments","brokerage","taxable",1_000_000, growth_rate=.06, equity_pct=1, cost_basis=700_000)],
        expenses=expenses or [], income_streams=[], mortgages=[], legacy_goal=0, state=state, monetary_convention=convention,
        withdrawal_strategy=strategy,
        economic=EconomicAssumptions(general_inflation=inflation,medical_inflation=inflation),
        social_security=SocialSecurity(primary_benefit_at_67=0,spouse_benefit_at_67=0)))


def test_resolver_is_pure_explicit_yields_win_and_estimates_are_traceable():
    cfg=config(); cfg["accounts"][0].update(investment_income_profile="balanced", interest_yield=.01, unrealized_gain_fraction=.3)
    before=deepcopy(cfg)
    resolved, readiness=resolve_inputs(cfg)
    assert cfg == before
    a=resolved["accounts"][0]
    assert a["interest_yield"] == .01
    assert a["dividend_yield"] == .015
    assert a["cost_basis"] == 700_000
    statuses={item["path"]:item["status"] for item in readiness["items"]}
    assert statuses["accounts[0].cost_basis"] == "estimated"
    assert statuses["accounts[0].dividend_yield"] == "estimated"
    assert statuses["balance_date"] == "missing"


@pytest.mark.parametrize("change", [{"investment_income_profile": []}, {"interest_yield": float("nan")}, {"dividend_yield": -1}, {"qualified_dividend_share": 2}, {"reinvest_distributions": "yes"}, {"unrealized_gain_fraction": -0.2}])
def test_invalid_income_inputs_fail_validation(change):
    cfg=config();cfg["accounts"][0].update(change)
    assert validate_config(cfg).errors


def test_total_only_plan_marks_account_access_unassessed(tmp_path):
    cfg=config();cfg["input_metadata"]={"account_breakdown":"missing"}
    path=tmp_path/'plan.json';path.write_text(json.dumps(cfg))
    p=RetirementPlanner.from_config(str(path))
    row=p.project_cash_flow()[0]
    assert not row["input_readiness"]["access_assessed"]
    assert row["accessible_spending_balance"] is None
    assert row["access_shortfall"] is None
    mc=MonteCarloEngine(p).run(num_simulations=2, return_volatility=0, seed=1)
    assert mc["access_failure_rate"] is None


@pytest.mark.parametrize("reinvest",[True,False])
def test_distributions_are_part_of_total_return_with_correct_basis(reinvest):
    a=Account("b","Investments","brokerage","taxable",1000, dividend_yield=.02,qualified_dividend_share=.75,reinvest_distributions=reinvest)
    balance,basis,ordinary,qualified,cash,gains=distribute(a,1000,1060,600)
    assert balance+cash == 1060
    assert ordinary == 5
    assert qualified == 15
    assert basis == (620 if reinvest else 600)
    assert balance == (1060 if reinvest else 1040)


def test_severe_loss_caps_distributions_and_retirement_accounts_compound_internally():
    a=Account("b","Investments","brokerage","taxable",1000, interest_yield=.05,dividend_yield=.05)
    assert sum(distribute(a,1000,10,600)[2:4]) == 10
    a.tax_treatment="roth"
    assert distribute(a,1000,1060,0) == (1060,0,0,0,0,0)


@pytest.mark.parametrize("reinvest",[True,False])
def test_annual_wealth_conservation_and_taxed_yields(reinvest):
    a=Account("b","Investments","brokerage","taxable",1_000_000,growth_rate=.06,equity_pct=1,cost_basis=700_000,interest_yield=.02,reinvest_distributions=reinvest)
    row=planner(a).project_cash_flow()[0]
    assert row["investment_income"] == 20_000
    assert row["ordinary_income_nominal"] >= 20_000
    assert row["net_worth"] == pytest.approx(1_060_000 - row["taxes"],abs=.1)
    assert row["taxes"] > 0
    assert row["investment_cash_income"] == (0 if reinvest else 20_000)
    assert row["magi_nominal"] >= 20_000
    if reinvest:
        assert row["taxable_basis_nominal"]["b"] > 700_000


def test_qualified_dividends_preferential_federal_and_ordinary_ca():
    p=planner(state="TX")
    ordinary=TaxableIncome(ordinary=200_000,investment_ordinary=100_000)
    qualified=TaxableIncome(ordinary=100_000,qualified_dividends=100_000)
    tax_o=p.calculate_taxes(2030,ordinary,filing_status=FilingStatus.SINGLE)
    tax_q=p.calculate_taxes(2030,qualified,filing_status=FilingStatus.SINGLE)
    assert tax_q < tax_o
    p.scenario.state="CA"
    ca_o=p.calculate_taxes(2030,ordinary,filing_status=FilingStatus.SINGLE)-tax_o
    ca_q=p.calculate_taxes(2030,qualified,filing_status=FilingStatus.SINGLE)-tax_q
    assert ca_o == pytest.approx(ca_q)


@pytest.mark.parametrize("reinvest",[True,False])
def test_distribution_real_nominal_equivalence(reinvest):
    a=Account("b","Investments","brokerage","taxable",1_000_000,growth_rate=.06,equity_pct=1,cost_basis=700_000,interest_yield=.02,dividend_yield=.02,qualified_dividend_share=.9,reinvest_distributions=reinvest)
    real=planner(a).project_cash_flow()
    nominal=planner(a,convention=MonetaryConvention.NOMINAL).project_cash_flow()
    for r,n in zip(real,nominal):
        factor=1.025**(r["year"]-2030)
        for key in ("net_worth","taxes","investment_income","income","investment_cash_income"):
            assert n[key]/factor == pytest.approx(r[key],abs=.1),key
        assert n["magi_nominal"] == pytest.approx(r["magi_nominal"],abs=.1)


def test_cuts_change_funded_giving_and_tax_deduction_before_tax_loop():
    gift=Expense("gift","Giving",10_000,date(2030,1,1),date(2033,1,1),category="charity",tax_deductible=True,is_must_spend=False,min_reduction=.5,funding_account="b",payment_kind="in_kind")
    basic=Expense("basic","Living",1000,date(2030,1,1),date(2033,1,1))
    p=planner(expenses=[gift,basic],strategy="dynamic")
    seen=[];calculate=p.calculate_taxes
    def capture(*args,**kwargs):
        seen.append(kwargs["charitable_deductions"])
        return calculate(*args,**kwargs)
    p.calculate_taxes=capture
    row=p.project_cash_flow()[0]
    assert row["planned_expenses"] == 132_000
    assert row["spending_cut"] == pytest.approx(13_200)
    assert row["expenses_by_id"]["basic"] == 12_000
    assert row["funded_expenses"] == pytest.approx(106_800)
    assert seen[0] == row["funded_expenses"]
    assert sum(row["expenses_by_category"].values()) == pytest.approx(row["expenses"])
    assert row["expenses"] == pytest.approx(118_800)
    assert row["capital_gains_nominal"] == pytest.approx(12_000 * (1 - 700_000/1_060_000))


def test_cut_reporting_uses_shared_deterministic_mc_loop():
    flexible=Expense("f","Trips",10_000,date(2030,1,1),date(2033,1,1),is_must_spend=False,min_reduction=.25)
    p=planner(expenses=[flexible],strategy="dynamic")
    rows=p.project_cash_flow()
    mc=MonteCarloEngine(p).run(num_simulations=2,seed=7,return_volatility=0)
    assert mc["spending_cut_frequency"] == 1
    assert mc["median_years_with_spending_cuts"] == sum(r["spending_cut"]>1 for r in rows)
    assert mc["maximum_spending_cut_fraction"] == pytest.approx(max(r["spending_cut_fraction"] for r in rows))


def test_capital_gain_distributions_are_taxed_reinvested_and_never_extra_return():
    a=Account("b","Investments","brokerage","taxable",1_000_000,growth_rate=.06,equity_pct=1,cost_basis=700_000,capital_gain_yield=.1)
    row=planner(a).project_cash_flow()[0]
    assert row['investment_income'] == 100_000
    assert row['capital_gain_distributions_nominal'] == 100_000
    assert row['capital_gains_nominal'] >= 100_000
    assert row['qualified_dividends_nominal'] == 0
    assert row['net_worth'] == pytest.approx(1_060_000-row['taxes'],abs=.1)
    assert row['taxable_basis_nominal']['b'] > 700_000


def test_ordinary_investment_income_gets_niit_without_payroll_tax():
    p=planner()
    classified=TaxableIncome(ordinary=300_000,investment_ordinary=300_000)
    unclassified=TaxableIncome(ordinary=300_000)
    assert p.calculate_taxes(2030,classified,filing_status=FilingStatus.SINGLE)-p.calculate_taxes(2030,unclassified,filing_status=FilingStatus.SINGLE) == pytest.approx(3800)


def test_reinvested_income_reduces_aca_support_and_updates_irmaa():
    health=Expense('h','Health',2000,date(2030,1,1),date(2033,1,1),category='medical')
    a=Account('b','Investments','brokerage','taxable',1_000_000,growth_rate=.06,equity_pct=1,cost_basis=1_000_000)
    p=planner(a,expenses=[health]);p.scenario.primary.coverage_type='aca'
    low=p.project_cash_flow()[0]
    a.interest_yield=.3
    high=p.project_cash_flow()[0]
    assert high['aca_subsidy'] < low['aca_subsidy']
    assert high['magi_nominal'] == pytest.approx(297_000)
    p.scenario.primary.birth_date=date(1965,1,1);p.scenario.primary.longevity_age=68;p.scenario.primary.coverage_type='medicare'
    rows=p.project_cash_flow()
    assert rows[2]['expenses'] > rows[0]['expenses']


def test_duplicate_expense_names_keep_separate_funding_and_reduction_limits():
    first=Expense('one','Same name',1000,date(2030,1,1),date(2033,1,1),is_must_spend=False,min_reduction=.5,funding_account='b')
    second=Expense('two','Same name',1000,date(2030,1,1),date(2033,1,1))
    row=planner(Account('b','Investments','brokerage','taxable',100_000,cost_basis=70_000),expenses=[first,second],strategy='dynamic').project_cash_flow()[0]
    assert row['expenses_by_id']['two'] == 12_000
    assert row['funded_expenses'] == pytest.approx(row['expenses_by_id']['one'])
    assert row['expenses_by_category']['Same name'] == pytest.approx(row['expenses'])


def test_older_wizard_null_ss_remains_disabled(tmp_path):
    cfg=config();cfg['social_security']=None
    path=tmp_path/'example.json';path.write_text(json.dumps(cfg))
    p=RetirementPlanner.from_config(str(path))
    assert p.scenario.social_security.primary_benefit_at_67 == 0
    assert p.scenario.social_security.spouse_benefit_at_67 == 0
