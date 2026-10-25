"""Anonymous regressions for access and nominal accounting boundaries."""
from dataclasses import replace
from datetime import date
import json

import pytest

from retirement_planner.access import reaches_age
from retirement_planner.engine import RetirementPlanner, WithdrawalEngine, CostBasisTracker
from retirement_planner.models import (Account, Person, Scenario, Expense, EconomicAssumptions,
    MonetaryConvention, Mortgage, HousingEvent, RothConversion, SocialSecurity)
from retirement_planner.config.validation import validate_config
from retirement_planner.simulators import MonteCarloEngine


def plan(accounts=None, expenses=None, convention=MonetaryConvention.REAL, **kwargs):
    return RetirementPlanner(Scenario(name="Fictional access case", description="", start_year=2026,
        primary=kwargs.pop("primary", Person("A", date(1990, 1, 1), date(2026, 1, 1), 43, coverage_type="none")),
        spouse=kwargs.pop("spouse", None), accounts=accounts or [], expenses=expenses or [], income_streams=[],
        mortgages=kwargs.pop("mortgages", []), monetary_convention=convention,
        economic=EconomicAssumptions(general_inflation=.025, medical_inflation=.025,
            equity_real_return=0, housing_appreciation=0), legacy_goal=0,
        social_security=SocialSecurity(primary_benefit_at_67=0,spouse_benefit_at_67=0), **kwargs))


def living(monthly=1000, **kwargs):
    return Expense("e", "Living", monthly, date(2026,1,1), date(2040,1,1), **kwargs)


def cash(amount=100_000):
    return Account("cash", "Cash", "checking", "taxable", amount, growth_rate=0,asset_class="cash")


def test_restricted_capital_is_access_failure_not_depletion():
    p=plan([Account("ira","IRA","trad_ira","pre_tax",1_000_000,asset_class="cash")],[living()])
    r=p.run_single_simulation(return_volatility=0,collect_projections=True)
    assert r["access_shortfall_year"] == 2026
    assert r["portfolio_depletion_year"] is None
    assert r["projections"][0]["withdrawals"] == 0
    assert r["projections"][0]["access_shortfall"] == 12_000
    assert r["success"] is False
    mc=MonteCarloEngine(p).run(num_simulations=2,seed=1,return_volatility=0)
    assert mc["access_failure_rate"] == 1
    assert mc["portfolio_depletion_rate"] == 0


def test_economic_depletion_and_explicit_legacy_policy():
    r=plan([cash(100)],[living()]).run_single_simulation(return_volatility=0)
    assert r["access_shortfall_year"] is None
    assert r["portfolio_depletion_year"] == 2026
    p=plan([Account("ira","IRA","trad_ira","pre_tax",1_000_000,asset_class="cash")],[living()],withdrawal_access_policy="unrestricted")
    r=p.run_single_simulation(return_volatility=0)
    assert r["access_shortfall_year"] is None
    assert any("bypasses" in m for m in r["model_warnings"])


def test_exact_half_birthday_uses_account_owner():
    assert not reaches_age(date(1966,7,15),59.5,date(2026,1,14))
    assert reaches_age(date(1966,7,15),59.5,date(2026,1,15))
    accounts={"a":Account("a","IRA","trad_ira","pre_tax",1000,owner="spouse")}
    engine=WithdrawalEngine(accounts,CostBasisTracker(),"penalty_free",
        {"primary":date(1950,1,1),"spouse":date(1966,7,15)},2026)
    assert engine.execute_withdrawals(500,{"a":1000},2026,76,60,sale_date=date(2026,1,14)) == []
    assert sum(w.amount for w in engine.execute_withdrawals(500,{"a":1000},2026,76,60,sale_date=date(2026,1,15))) == 500


def test_roth_regular_basis_shared_once_across_iras():
    accounts=[Account("r1","R1","roth_ira","roth",10_000,roth_contribution_basis=5000,asset_class="cash"),
              Account("r2","R2","roth_ira","roth",10_000,asset_class="cash")]
    row=plan(accounts,[living()]).project_cash_flow()[0]
    assert row["withdrawals"] == pytest.approx(5000)
    assert row["access_shortfall"] == pytest.approx(7000)
    assert row["accessible_spending_balance"] == pytest.approx(5000)


def test_roth_principal_not_reused_by_tax_trials_or_later_years():
    a=Account("r","Roth","roth_ira","roth",100_000,roth_contribution_basis=18_000,asset_class="cash")
    rows=plan([a],[living()]).project_cash_flow()
    assert rows[0]["withdrawals"] == pytest.approx(12_000)
    assert rows[1]["withdrawals"] == pytest.approx(6000/1.025)
    assert rows[2]["withdrawals"] == 0


def test_conversion_locked_until_fifth_tax_year():
    a=Account("r","Roth","roth_ira","roth",100_000,asset_class="cash",
              roth_conversion_basis=[dict(year=2024,amount=10_000)],roth_first_contribution_year=2024)
    rows=plan([a],[living()]).project_cash_flow()
    assert rows[0]["withdrawals"] == rows[1]["withdrawals"] == rows[2]["withdrawals"] == 0
    assert rows[3]["withdrawals"] == pytest.approx(10_000/1.025**3)
    assert rows[4]["withdrawals"] == 0


def test_new_conversion_cohort_and_qualified_hsa_funding():
    accounts=[cash(200_000),Account("ira","IRA","trad_ira","pre_tax",100_000,asset_class="cash"),
              Account("r","Roth","roth_ira","roth",0,asset_class="cash"),
              Account("h","HSA","hsa","tax_exempt",50_000,asset_class="cash")]
    rc=RothConversion("rc","Conversion","ira","r",date(2026,1,1),date(2027,1,1),10_000)
    expense=living(funding_account="h",hsa_qualified=True,category="medical")
    row=plan(accounts,[expense],roth_conversions=[rc]).project_cash_flow()[0]
    assert row["funded_expenses"] == 12_000
    assert row["withdrawals_by_account"]["h"] == 0
    assert row["roth_conversion_schedule"] == [dict(owner="primary",conversion_year=2026,penalty_free_year=2031,remaining_nominal=10_000)]


def test_hsa_cannot_fund_young_retiree_ordinary_spending():
    row=plan([Account("h","HSA","hsa","tax_exempt",50_000,asset_class="cash")],[living()]).project_cash_flow()[0]
    assert row["withdrawals"] == 0
    assert row["access_shortfall"] == 12_000


def test_roth_earnings_require_both_clocks():
    a=Account("r","Roth","roth_ira","roth",100_000,asset_class="cash",roth_first_contribution_year=2024)
    person=Person("A",date(1960,1,1),date(2026,1,1),70,coverage_type="none")
    rows=plan([a],[living()],primary=person).project_cash_flow()
    assert rows[0]["withdrawals"] == 0
    assert rows[3]["withdrawals"] >= 12_000


@pytest.mark.parametrize("value", ["penalty_free","unrestricted"])
def test_access_config_roundtrip(tmp_path,value):
    config={"start_year":2026,"withdrawal_access_policy":value,
        "primary":{"name":"A","birth_date":"1990-01-01","retirement_date":"2026-01-01"},
        "accounts":[{"id":"r","name":"Roth","type":"roth_ira","tax_treatment":"roth","balance":20_000,
            "roth_contribution_basis":5000,"roth_conversion_basis":[{"year":2023,"amount":10_000}],"roth_first_contribution_year":2020}]}
    validate_config(config,strict=True).raise_for_errors()
    path=tmp_path/'plan.json';path.write_text(json.dumps(config))
    p=RetirementPlanner.from_config(str(path))
    assert p.scenario.withdrawal_access_policy == value
    assert p.scenario.accounts[0].roth_contribution_basis == 5000


@pytest.mark.parametrize("convention", [MonetaryConvention.REAL,MonetaryConvention.NOMINAL])
def test_inflation_only_sale_has_nominal_gain(convention):
    a=Account("b","Brokerage","brokerage","taxable",100_000,cost_basis=100_000,asset_class="equity",equity_pct=1)
    row=plan([a],[replace(living(5000),start_date=date(2027,1,1))],convention=convention).project_cash_flow()[1]
    assert row["capital_gains_nominal"] > 1000
    assert row["capital_gains_nominal"] == pytest.approx(row["withdrawals"]*(1.025 if convention==MonetaryConvention.REAL else 1)*(1-1/1.025))


def test_nominal_basis_stays_fixed_without_transactions():
    a=Account("b","Brokerage","brokerage","taxable",100_000,cost_basis=60_000,asset_class="equity")
    assert all(row["taxable_basis_nominal"]["b"] == pytest.approx(60_000) for row in plan([a]).project_cash_flow())


@pytest.mark.parametrize("strategy", ["fixed","dynamic","guardrails","percent_of_portfolio","floor_ceiling"])
def test_real_nominal_parity_for_basis_debt_sale_and_conversion(strategy):
    accounts=[cash(100_000),Account("b","Brokerage","brokerage","taxable",1_000_000,cost_basis=500_000,asset_class="equity",equity_pct=1),
              Account("home","Home","real_estate","taxable",400_000,cost_basis=100_000,liquid=False,growth_rate=0),
              Account("ira","IRA","trad_ira","pre_tax",100_000,asset_class="cash"),
              Account("r","Roth","roth_ira","roth",0,asset_class="cash")]
    mortgage=Mortgage("m","Loan","home",100_000,.05,1000,date(2026,1,1),date(2040,1,1),deduction_kind="itemized")
    sale=HousingEvent("sale","Sale",date(2029,7,1),sale_price=600_000,property_id="home",goes_to_account="b",selling_costs=10_000,exclusion_eligible=False)
    rc=RothConversion("rc","Conversion","ira","r",date(2027,1,1),date(2028,1,1),10_000)
    kwargs=dict(mortgages=[mortgage],housing_events=[sale],roth_conversions=[rc],withdrawal_strategy=strategy)
    real=plan(accounts,[living(10_000)],**kwargs).project_cash_flow()
    nominal=plan(accounts,[living(10_000)],convention=MonetaryConvention.NOMINAL,**kwargs).project_cash_flow()
    for r,n in zip(real,nominal):
        factor=1.025**(r['year']-2026)
        for key in ('income','expenses','taxes','net_worth','total_liabilities','withdrawals'):
            assert r[key]*factor == pytest.approx(n[key],abs=.20), (r['year'],key,r[key]*factor,n[key])
        assert r['taxable_basis_nominal'] == pytest.approx(n['taxable_basis_nominal'],abs=.01)
        assert r['mortgage_balances_nominal'] == pytest.approx(n['mortgage_balances_nominal'],abs=.01)


def test_fixed_nominal_mortgage_deflates_in_real_projection():
    m=Mortgage("m","Loan","home",100_000,0,1000,date(2026,1,1),date(2040,1,1))
    rows=plan([cash(1_000_000)],mortgages=[m]).project_cash_flow()
    assert rows[1]['expenses'] == pytest.approx(12_000/1.025)
    assert rows[1]['mortgage_balances_nominal']['m'] == pytest.approx(76_000)
    assert rows[1]['total_liabilities'] == pytest.approx(76_000/1.025)


def test_purchase_new_loan_and_arm_reset_reconcile():
    accounts=[Account("b","Brokerage","brokerage","taxable",1_000_000,cost_basis=500_000,asset_class="equity",equity_pct=1)]
    event=HousingEvent("buy","Purchase",date(2028,7,1),purchase_price=200_000,
        mortgage_amount=100_000,mortgage_rate=.05,purchase_costs=5000,
        funding_account="b",property_id="home")
    real=plan(accounts,[living()],housing_events=[event]).project_cash_flow()
    nominal=plan(accounts,[living()],convention=MonetaryConvention.NOMINAL,housing_events=[event]).project_cash_flow()
    for r,n in zip(real,nominal):
        factor=1.025**(r['year']-2026)
        for key in ('expenses','taxes','net_worth','total_liabilities'):
            assert r[key]*factor == pytest.approx(n[key],abs=.20)
        assert r['mortgage_balances_nominal'] == pytest.approx(n['mortgage_balances_nominal'])
    assert real[2]['capital_gains_nominal'] > 50_000  # down payment is a taxable sale
    m=Mortgage("m","ARM","home",100_000,.04,1000,date(2026,1,1),date(2040,1,1),
        rate_changes=[dict(date="2028-01-01",interest_rate=.08,monthly_payment=2000)])
    r=plan([cash(1_000_000)],mortgages=[m]).project_cash_flow()[2]
    assert r['expenses'] == pytest.approx(24_000/1.025**2)


def test_healthcare_and_social_security_use_nominal_tax_units():
    person=Person("A",date(1962,1,1),date(2026,1,1),73,coverage_type="auto")
    accounts=[Account("b","Brokerage","brokerage","taxable",1_000_000,cost_basis=200_000,asset_class="equity",equity_pct=1)]
    real_planner=plan(accounts,[living(10_000,category="medical")],primary=person)
    nominal_planner=plan(accounts,[living(10_000,category="medical")],primary=person,convention=MonetaryConvention.NOMINAL)
    for p in (real_planner,nominal_planner):
        p.scenario.social_security.primary_benefit_at_67=2000
    for r,n in zip(real_planner.project_cash_flow(),nominal_planner.project_cash_flow()):
        factor=1.025**(r['year']-2026)
        for key in ('income','taxes','expenses','aca_subsidy','net_worth'):
            assert r[key]*factor == pytest.approx(n[key],abs=.20), (r['year'],key)


def test_rmd_prior_year_nominal_reference_and_fees_reconcile():
    import numpy as np
    person=Person("A",date(1950,1,1),date(2026,1,1),83,coverage_type="none")
    accounts=[cash(),Account("ira","IRA","trad_ira","pre_tax",500_000,expense_ratio=.001,asset_class="equity",equity_pct=1)]
    real=plan(accounts,[living()],primary=person).run_single_simulation(rng=np.random.default_rng(42),collect_projections=True)['projections']
    nominal=plan(accounts,[living()],primary=person,convention=MonetaryConvention.NOMINAL).run_single_simulation(rng=np.random.default_rng(42),collect_projections=True)['projections']
    for r,n in zip(real,nominal):
        factor=1.025**(r['year']-2026)
        assert r['withdrawals']*factor == pytest.approx(n['withdrawals'],abs=.20)
        assert r['taxes']*factor == pytest.approx(n['taxes'],abs=.20)
        assert r['net_worth']*factor == pytest.approx(n['net_worth'],abs=.20)


@pytest.mark.parametrize("fields", [
    dict(roth_contribution_basis=-1),dict(roth_first_contribution_year=2030),
    dict(roth_conversion_basis=[dict(year=2030,amount=1)]),
    dict(roth_conversion_basis=[dict(year=2020,amount=-1)]),
])
def test_invalid_access_records_rejected(fields):
    config=dict(start_year=2026,primary=dict(name="A",birth_date="1990-01-01",retirement_date="2026-01-01"),
        accounts=[dict(id="r",name="Roth",type="roth_ira",tax_treatment="roth",balance=1000,**fields)])
    assert not validate_config(config,strict=True).valid


def test_roth_workplace_clock_not_borrowed_from_ira():
    accounts={"ira":Account("ira","IRA","roth_ira","roth",100,roth_first_contribution_year=2000),
              "k":Account("k","Plan","roth_401k","roth",10_000,roth_first_contribution_year=2025)}
    e=WithdrawalEngine(accounts,CostBasisTracker(),"penalty_free",start_year=2026)
    balances={"ira":0,"k":10_000}
    assert e.execute_withdrawals(1000,balances,2026,65,65) == []


def test_retirement_tax_treatment_inferred_and_conflicts_rejected(tmp_path):
    config=dict(start_year=2026,primary=dict(name="A",birth_date="1990-01-01",retirement_date="2026-01-01"),
        accounts=[dict(id="k",name="Plan",type="401k",balance=100_000)])
    p=tmp_path/'input.json';p.write_text(json.dumps(config))
    assert RetirementPlanner.from_config(str(p)).accounts['k'].tax_treatment == 'pre_tax'
    config['accounts'][0]['tax_treatment']='taxable'
    assert not validate_config(config,strict=True).valid


def test_generic_events_cannot_bypass_restricted_access():
    base=dict(start_year=2026,primary=dict(name="A",birth_date="1990-01-01",retirement_date="2026-01-01"),
        accounts=[dict(id="k",name="Plan",type="401k",balance=100_000),
                  dict(id="c",name="Cash",type="checking",balance=0)])
    for extra in [dict(windfalls=[dict(source_account='k',goes_to_account='c')]),
                  dict(housing_events=[dict(funding_account='k')])]:
        assert not validate_config({**base,**extra},strict=True).valid


def test_unknown_programmatic_access_policy_rejected():
    with pytest.raises(ValueError,match="withdrawal_access_policy"):
        plan([cash()],withdrawal_access_policy="guess")


def test_house_purchase_from_bank_cash_does_not_realize_capital_gains():
    event=HousingEvent("buy","Purchase",date(2028,7,1),purchase_price=50_000,
        funding_account="cash",property_id="home")
    row=plan([cash(100_000)],housing_events=[event]).project_cash_flow()[2]
    assert row['capital_gains_nominal'] == 0


def test_expense_funded_by_taxable_sale_realizes_gain():
    a=Account("b","Brokerage","brokerage","taxable",100_000,cost_basis=50_000,asset_class="equity",equity_pct=1)
    e=replace(living(1000,funding_account='b'),start_date=date(2027,1,1))
    real=plan([a],[e]).project_cash_flow()[1]
    nominal=plan([a],[e],convention=MonetaryConvention.NOMINAL).project_cash_flow()[1]
    assert real['capital_gains_nominal'] > 6000
    assert real['capital_gains_nominal'] == pytest.approx(nominal['capital_gains_nominal'])
