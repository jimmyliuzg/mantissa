"""Economic regressions from the October 2026 engine review (fictional data)."""
import json
from datetime import date
from dataclasses import replace

import numpy as np
import pytest

from retirement_planner.engine import RetirementPlanner, CostBasisTracker, WithdrawalEngine
from retirement_planner.models import (Account, Person, Scenario, EconomicAssumptions,
    Expense, IncomeStream, Windfall, HousingEvent, Mortgage, MonetaryConvention,
    RothConversion, RolloverEvent, TaxableIncome, RSUGrant)
from retirement_planner.tax_law import TaxLawRegistry, FilingStatus, bracket_tax
from retirement_planner.config.validation import validate_config
from retirement_planner.fixes import process_housing_event


def planner(accounts=None, incomes=None, expenses=None, **kwargs):
    return RetirementPlanner(Scenario(
        name="Fictional regression", description="", start_year=2026,
        primary=Person("A", date(1990, 1, 1), date(2030, 1, 1), 38),
        spouse=None, economic=EconomicAssumptions(general_inflation=0.0),
        accounts=accounts or [], income_streams=incomes or [],
        expenses=expenses or [], mortgages=kwargs.pop("mortgages", []),
        **kwargs))


def wage(amount=100_000, owner="primary"):
    return IncomeStream("salary", "Salary", owner, amount / 12,
                        date(2026, 1, 1), date(2030, 1, 1))


def cash(balance=100_000):
    return Account("cash", "Cash", "checking", "taxable", balance,
                   growth_rate=0, asset_class="cash", contribution_priority=10)


def test_config_honors_nominal_start_year_and_cash(tmp_path):
    cfg = {"primary": {"name":"A", "birth_date":"1990-01-01", "retirement_date":"2030-01-01"},
           "start_year":2027, "monetary_convention":"nominal", "accounts":[
               {"id":"cash", "name":"Cash", "type":"money_market", "balance":1000,
                "asset_class":"cash", "growth_rate":.02, "cost_basis":500}]}
    path = tmp_path / "plan.json"; path.write_text(json.dumps(cfg))
    p = RetirementPlanner.from_config(str(path))
    assert p.start_year == 2027
    assert p.scenario.monetary_convention == MonetaryConvention.NOMINAL
    assert p.accounts["cash"].cost_basis == 500
    assert p.accounts["cash"].asset_class == "cash"


def test_cash_and_property_are_unaffected_by_equity_crash():
    accounts = [cash(), Account("home", "Home", "real_estate", "taxable", 500_000, growth_rate=0, liquid=False),
                Account("bond", "Bond", "brokerage", "taxable", 100_000, asset_class="bond")]
    p = planner(accounts)
    p._historical_return_override = [-.9]
    crash = p.run_single_simulation(return_volatility=0, collect_projections=True)["projections"][0]
    p._historical_return_override = [.9]
    boom = p.run_single_simulation(return_volatility=0, collect_projections=True)["projections"][0]
    assert crash["account_balances"] == boom["account_balances"]


def test_identical_stock_accounts_share_the_same_market_shock():
    a = Account("a", "A", "brokerage", "taxable", 100_000, asset_class="equity")
    b = replace(a, id="b", balance=200_000)
    p = planner([a,b])
    row = p.run_single_simulation(rng=np.random.default_rng(3), collect_projections=True)["projections"][0]
    assert row["account_balances"]["b"] == pytest.approx(2 * row["account_balances"]["a"])


def test_optimistic_and_pessimistic_cma_change_returns():
    p = planner([Account("a", "A", "brokerage", "taxable", 100_000, asset_class="equity")])
    assert p.project_cash_flow("optimistic")[0]["net_worth"] > p.project_cash_flow("pessimistic")[0]["net_worth"]


def test_partial_sale_realizes_proportional_gain_and_preserves_remaining_basis():
    a = Account("a", "A", "brokerage", "taxable", 200, cost_basis=100)
    tracker = CostBasisTracker({"a":100})
    engine = WithdrawalEngine({"a":a}, tracker); balances={"a":200}
    result=engine.execute_withdrawals(50, balances, 2026, 40, 40)
    assert result[0].capital_gain == 25
    assert balances["a"] == 150
    assert tracker.get_basis("a") == 75


def test_spending_and_savings_change_deterministic_balances():
    spending=Expense("e","Living",1000,date(2026,1,1),date(2029,1,1))
    p=planner([cash()],expenses=[spending])
    assert p.project_cash_flow()[0]["net_worth"] == pytest.approx(88_000)
    p=planner([cash()],incomes=[wage()],expenses=[spending])
    row=p.project_cash_flow()[0]
    assert row["net_worth"] == pytest.approx(100_000 + row["net_cash_flow"])
    assert row["net_worth"] > 100_000
    mc=p.run_single_simulation(return_volatility=0,collect_projections=True)["projections"]
    assert [r["net_worth"] for r in mc] == [r["net_worth"] for r in p.project_cash_flow()]


def test_pretax_contributions_reduce_taxes_and_match_does_not_reduce_cash():
    k=Account("k","401k","401k","pre_tax",0,growth_rate=0,contribution_priority=1,
              annual_contribution_cap=24_500,employer_match=.5,employer_match_limit=1000)
    baseline=planner([cash()],incomes=[wage()]).project_cash_flow()[0]
    row=planner([k,cash()],incomes=[wage()]).project_cash_flow()[0]
    assert row["taxes"] < baseline["taxes"]
    assert row["contributions"]["k"] == 25_000
    assert row["net_worth"] - baseline["net_worth"] == pytest.approx(baseline["taxes"] - row["taxes"] + 500)


def test_401k_limit_is_shared_by_owner_and_honors_zero_year():
    accounts=[Account(str(i),str(i),"401k","pre_tax",0,contribution_priority=i+1,annual_contribution_cap=24_500) for i in range(2)]
    accounts[0].contribution_caps_by_year={2027:0}
    engine=WithdrawalEngine({a.id:a for a in accounts},CostBasisTracker())
    result=engine.contribute({"0":0,"1":0},100_000,2026,{"primary"},{"primary":36})
    assert sum(result.values()) == 24_500
    result=engine.contribute({"0":0,"1":0},100_000,2027,{"primary"},{"primary":37})
    assert "0" not in result
    assert engine.contribute({"0":0,"1":0},100_000,2026,set(),{}) == {}


def test_2026_published_tax_amounts_and_future_fixed_thresholds():
    registry=TaxLawRegistry(); law=registry.law_for_year(2026)
    assert law.standard_deduction[FilingStatus.MFJ] == 32_200
    assert law.federal_brackets[FilingStatus.MFJ][0].upper == 24_800
    assert law.ltcg_brackets[FilingStatus.MFJ][0].upper == 98_900
    assert law.estate_exemption_single == 15_000_000
    assert law.ca_standard_deduction[FilingStatus.SINGLE] == 5900
    assert law.ca_brackets[-1].rate == .123
    assert registry.law_for_year(2030).salt_cap == 10_000
    assert registry.law_for_year(2040).niit_thresholds[FilingStatus.MFJ] == 250_000


def test_deduction_shelters_capital_gains_when_no_ordinary_income():
    p=planner(state="TX"); income=TaxableIncome(0,90_000,0,90_000)
    assert p.calculate_taxes(2026,income,filing_status=FilingStatus.MFJ) == 0


def test_2026_salt_phaseout_and_charity_floor():
    p=planner(state="TX"); law=TaxLawRegistry().law_for_year(2026)
    # MFJ taxable 400k-40.4k; SALT exceeds the standard deduction and no AMT here.
    ti=TaxableIncome(400_000,0,0,400_000)
    assert p.calculate_taxes(2026,ti,salt_paid=50_000,filing_status=FilingStatus.MFJ) == pytest.approx(bracket_tax(359_600,law.federal_brackets[FilingStatus.MFJ]))
    high=TaxableIncome(750_000,0,0,750_000)
    assert p.calculate_taxes(2026,high,salt_paid=50_000) == p.calculate_taxes(2026,high,salt_paid=10_000)
    # $100k gift has a $2k floor at $400k AGI; 98k plus capped SALT.
    assert p.calculate_taxes(2026,ti,salt_paid=50_000,charitable_deductions=100_000,filing_status=FilingStatus.MFJ) == pytest.approx(bracket_tax(261_600,law.federal_brackets[FilingStatus.MFJ]))


def test_payroll_tax_uses_individual_social_security_caps():
    p=planner(state="TX"); ti=TaxableIncome(500_000,0,0,500_000)
    base=p.calculate_taxes(2026,ti)
    total=p.calculate_taxes(2026,ti,wages_by_owner={"primary":250_000,"spouse":250_000})
    assert total-base == pytest.approx(2*184_500*.062 + 500_000*.0145 + 250_000*.009)


def test_in_kind_gift_reduces_assets_and_basis_without_capital_gain():
    gift=Expense("gift","Gift",0,date(2026,1,1),date(2027,1,1),is_one_time=True,
                 one_time_date=date(2026,1,1),one_time_amount=30_000,category="charity",tax_deductible=True,
                 funding_account="cash",payment_kind="in_kind")
    row=planner([cash()],expenses=[gift]).project_cash_flow()[0]
    assert row["net_worth"] == pytest.approx(70_000)
    assert row["taxes"] == 0
    assert row["cash_expenses"] == 0
    assert row["expenses"] == 30_000


def test_529_expense_debits_529_and_not_brokerage():
    college=Expense("college","College",1000,date(2026,1,1),date(2027,1,1),category="education",funding_account="529")
    edu=Account("529","529","529","tax_exempt",50_000,growth_rate=0)
    row=planner([edu,cash()],expenses=[college]).project_cash_flow()[0]
    assert row["account_balances"]["529"] == 38_000
    assert row["account_balances"]["cash"] == 100_000


@pytest.mark.parametrize("taxable",[False,True])
def test_windfall_tax_flag_affects_income_tax(taxable):
    wf=Windfall("gift","Event",100_000,date(2026,1,1),goes_to_account="cash",is_taxable=taxable)
    row=planner([cash()],windfalls=[wf]).project_cash_flow()[0]
    assert (row["taxes"] > 0) == taxable
    assert row["net_worth"] == pytest.approx(200_000-row["taxes"])


def test_transfers_are_wealth_neutral_and_preserve_aggregate_basis():
    wf=Windfall("move","Move",10_000,date(2026,1,1),goes_to_account="b",source_account="cash")
    b=Account("b","B","brokerage","taxable",0,growth_rate=0)
    row=planner([cash(),b],windfalls=[wf]).project_cash_flow()[0]
    assert row["net_worth"] == 100_000
    assert row["taxes"] == 0
    assert row["account_balances"]["b"] == 10_000


def test_rollover_can_feed_same_year_conversion():
    accounts=[cash(),Account("k","K","401k","pre_tax",40_000,growth_rate=0),
              Account("i","I","trad_ira","pre_tax",0,growth_rate=0),Account("r","R","roth_ira","roth",0,growth_rate=0)]
    ro=RolloverEvent("ro","Rollover",date(2026,1,1),"k","i")
    rc=RothConversion("rc","Convert","i","r",date(2026,1,1),date(2027,1,1),20_000)
    row=planner(accounts,rollover_events=[ro],roth_conversions=[rc]).project_cash_flow()[0]
    assert row["account_balances"]["r"] == 20_000
    assert row["account_balances"]["k"] == 0
    assert row["taxes"] > 0


def test_rmd_uses_prior_december_balance_and_age75_for_1960_birth():
    a=Account("i","IRA","trad_ira","pre_tax",100_000,growth_rate=.10)
    p=planner([a,cash()]); p.scenario.primary.birth_date=date(1960,1,1);p.scenario.primary.longevity_age=75
    rows=p.project_cash_flow()
    assert rows[7]["year"] == 2033
    assert rows[7]["withdrawals"] == 0 # age73, no expense shortfall
    previous=rows[8]["account_balances"]["i"]
    assert rows[9]["withdrawals"] == pytest.approx(previous / 24.6)


def test_sale_removes_full_property_and_keeps_unrelated_mortgage():
    he=HousingEvent("sell","Sell",date(2026,6,1),sale_price=500_000,property_id="home",goes_to_account="cash",selling_costs=25_000)
    balances={"home":550_000,"cash":0}; liabilities={"home_m":100_000,"rental_m":200_000}
    result=process_housing_event(he,2026,balances,liabilities,400_000,mortgage_property_map={"home_m":"home","rental_m":"rental"},defer_tax=True)
    assert balances["home"] == 0
    assert balances["cash"] == 375_000
    assert liabilities["rental_m"] == 200_000
    assert result.taxable_gain == 0


def test_unfunded_purchase_preserves_money_and_flags_shortfall():
    he=HousingEvent("buy","Buy",date(2026,1,1),purchase_price=500_000,down_payment=100_000,mortgage_amount=400_000,property_id="home",funding_account="cash",purchase_costs=10_000)
    balances={"cash":10_000}; liabilities={}
    result=process_housing_event(he,2026,balances,liabilities,0,defer_tax=True)
    assert result.funding_shortfall == 100_000
    assert sum(balances.values()) - sum(liabilities.values()) == 0 # 10k initial wealth minus 10k closing costs
    assert planner([cash(10_000)],housing_events=[he]).run_single_simulation(return_volatility=0)["out_of_savings_year"] == 2026


def test_sale_stops_old_mortgage_and_arm_reset_changes_payment():
    m=Mortgage("m","Mortgage","home",100_000,.06,1000,date(2026,1,1),date(2056,1,1),deduction_kind="itemized",rate_changes=[{"date":"2027-01-01","interest_rate":.08,"monthly_payment":1200}])
    he=HousingEvent("sell","Sell",date(2026,6,1),sale_price=200_000,property_id="home",goes_to_account="cash")
    p=planner([cash()],mortgages=[m],housing_events=[he])
    exp=p.calculate_annual_expenses(2026,mortgage_balances={"m":100_000})
    assert exp["total"] == 5000
    assert exp["mortgage_interest"] > 0
    p.scenario.housing_events=[]
    exp=p.calculate_annual_expenses(2027,mortgage_balances={"m":90_000})
    assert exp["total"] == 14_400


def test_partial_year_employment_and_explicit_vest_dates():
    p=planner()
    grant=RSUGrant("g",date(2025,1,1),400,"quarterly",periodic_shares=25,first_vest_date=date(2025,4,1))
    assert p._vested_shares_in_year(grant,2026,date(2026,7,1)) == 50
    grant.status="cancelled"
    assert p._vested_shares_in_year(grant,2026) == 0


def test_validation_rejects_nonfinite_and_cross_spouse_conversion():
    cfg={"primary":{"name":"A","birth_date":"1990-01-01","retirement_date":"2030-01-01"},"accounts":[
        {"id":"i","name":"IRA","type":"trad_ira","tax_treatment":"pre_tax","owner":"primary","balance":100},
        {"id":"r","name":"Roth","type":"roth_ira","tax_treatment":"roth","owner":"spouse","balance":0}],
        "roth_conversions":[{"source_account":"i","target_account":"r"}]}
    assert any("same owner" in e.message for e in validate_config(cfg).errors)
    cfg["accounts"][0]["balance"]=float("nan")
    assert any("finite" in e.message for e in validate_config(cfg).errors)


def test_new_purchase_mortgage_payments_are_charged_in_purchase_year():
    he=HousingEvent("buy","Buy",date(2026,6,1),purchase_price=500_000,down_payment=100_000,mortgage_amount=400_000,mortgage_rate=0,property_id="home",funding_account="cash")
    row=planner([cash(200_000)],housing_events=[he]).project_cash_flow()[0]
    assert row["expenses_by_category"]["Mortgage - buy_mortgage"] == pytest.approx(400_000/360*6)
    assert row["cash_expenses"] == pytest.approx(400_000/360*6)
    assert row["net_worth"] == pytest.approx(200_000) # principal swaps cash for home equity


def test_surplus_without_savings_order_is_preserved_and_available_later():
    a=cash(0); a.contribution_priority=0
    p=planner([a],incomes=[wage()])
    row=p.project_cash_flow()[0]
    assert row["account_balances"]["cash"] == pytest.approx(100_000-row["taxes"])
    p=planner([],incomes=[wage()])
    row=p.project_cash_flow()[0]
    assert row["account_balances"]["_unallocated_cash"] == pytest.approx(100_000-row["taxes"])


def test_owner_401k_cannot_use_passive_income_without_wages():
    a=Account("k","401k","401k","pre_tax",0,contribution_priority=1,annual_contribution_cap=24_500)
    rental=wage(); rental.is_w2=False; rental.is_passive=True
    row=planner([a,cash()],incomes=[rental]).project_cash_flow()[0]
    assert "k" not in row["contributions"]


def test_model_exposes_asof_basis_and_retirement_access_limits():
    a=Account("b","Brokerage","brokerage","taxable",100)
    with pytest.warns(UserWarning,match="whole years"):
        p=planner([a],balance_date=date(2026,10,1))
    messages=p.run_single_simulation(return_volatility=0)["model_warnings"]
    assert any("opening balances" in m for m in messages)
    assert any("cost_basis" in m for m in messages)
    assert any("five-year" in m for m in messages)


def test_new_mortgage_interest_deduction_is_wired_into_taxes():
    he=HousingEvent("buy","Buy",date(2026,6,1),purchase_price=500_000,down_payment=100_000,mortgage_amount=400_000,mortgage_rate=.1,property_id="home",funding_account="cash")
    before=planner([cash(200_000)],incomes=[wage(200_000)],housing_events=[he]).project_cash_flow()[0]
    he.mortgage_deduction_kind="itemized"
    after=planner([cash(200_000)],incomes=[wage(200_000)],housing_events=[he]).project_cash_flow()[0]
    assert after["taxes"] < before["taxes"]


@pytest.mark.parametrize("stress,mandatory,expected", [(0,False,50_000),(.5,False,25_000),(1,False,0),(1,True,50_000)])
def test_one_time_giving_cuts_debit_and_deduction_together(stress, mandatory, expected):
    gift=Expense("gift","Stock gift",0,date(2026,1,1),date(2027,1,1),
                 is_one_time=True,one_time_amount=50_000,one_time_date=date(2026,12,1),
                 category="charity",is_must_spend=mandatory,min_reduction=1,
                 tax_deductible=True,funding_account="cash",payment_kind="in_kind")
    p=planner([cash()],incomes=[wage()],expenses=[gift])
    assert p.calculate_annual_expenses(2026,stress_level=stress)["by_category"]["Stock gift"] == expected
    assert "Stock gift" not in p.calculate_annual_expenses(2027,stress_level=stress)["by_category"]
    row=p.project_cash_flow(stress_level=stress)[0]
    reference=planner([cash()],incomes=[wage()],expenses=[replace(gift,one_time_amount=expected,min_reduction=0)]).project_cash_flow()[0]
    assert row["funded_expenses"] == expected
    assert row["taxes"] == pytest.approx(reference["taxes"])
    no_gift=planner([cash()],incomes=[wage()]).project_cash_flow()[0]
    if expected > 0:
        assert row["taxes"] < no_gift["taxes"]
    else:
        assert row["taxes"] == pytest.approx(no_gift["taxes"])
    assert row["account_balances"] == pytest.approx(reference["account_balances"])
    assert row["net_worth"] == pytest.approx(reference["net_worth"])


def test_stress_command_lists_discretionary_one_time_giving(tmp_path):
    from click.testing import CliRunner
    from retirement_planner.cli import main
    cfg={"start_year":2026,"primary":{"name":"A","birth_date":"1990-01-01","retirement_date":"2030-01-01","longevity_age":38},
         "accounts":[{"id":"cash","name":"Cash","type":"checking","balance":100_000,"asset_class":"cash","growth_rate":0}],
         "expenses":[{"id":"gift","name":"Stock gift","monthly_amount":0,"start_date":"2026-01-01","end_date":"2027-01-01", "is_one_time":True,"one_time_amount":10_000,"one_time_date":"2026-12-01","is_must_spend":False,"min_reduction":1}]}
    path=tmp_path/"plan.json";path.write_text(json.dumps(cfg))
    result=CliRunner().invoke(main,["stress","-c",str(path),"-n","1","--levels","1","--seed","42"])
    assert result.exit_code == 0, result.output
    assert "Stock gift: -100% max cut" in result.output
