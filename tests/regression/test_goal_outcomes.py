"""Fictional end-to-end cases for independent funding and legacy goals."""
from datetime import date
import json

import pytest

from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import (Account, EconomicAssumptions, Expense, HousingEvent,
    MonetaryConvention, Person, Scenario, SocialSecurity)
from retirement_planner.outcomes import OutcomeTracker
from retirement_planner.reports import generate_summary_report, generate_mc_report, outcome_metric_rows
from retirement_planner.simulators import MonteCarloEngine


def planner(balance=100_000, spend=12_000, goal=0, *, restricted=0,
            flexible=False, convention=MonetaryConvention.REAL, last_age=40,
            housing=None, policy="penalty_free"):
    return RetirementPlanner(Scenario(name="Fictional goals", description="",start_year=2030,
        primary=Person("Example",date(1990,1,1),date(2030,1,1),last_age,coverage_type="none"),spouse=None,
        accounts=[Account("cash","Cash","checking","taxable",balance,growth_rate=0,asset_class="cash"),
                  Account("ira","IRA","trad_ira","pre_tax",restricted,growth_rate=0,asset_class="cash")],
        expenses=[Expense("living","Living",spend/12,date(2030,1,1),date(2040,1,1),
                         is_must_spend=not flexible,min_reduction=.25 if flexible else 0)] if spend else [],
        income_streams=[],mortgages=[],housing_events=housing or [],legacy_goal=goal,
        monetary_convention=convention,withdrawal_access_policy=policy,
        withdrawal_strategy="dynamic" if flexible else "fixed", state="TX",
        economic=EconomicAssumptions(general_inflation=.025,medical_inflation=.025,housing_appreciation=0),
        social_security=SocialSecurity(primary_benefit_at_67=0,spouse_benefit_at_67=0)))


def run(p):
    return p.run_single_simulation(return_volatility=0,collect_projections=True)


def mc(p):
    return MonteCarloEngine(p).run(num_simulations=3,return_volatility=0,seed=17)


def test_spending_covered_despite_legacy_target_missed():
    result=run(planner(goal=200_000));o=result['outcomes']
    assert o['planned_spending_met'] and o['adjusted_spending_met']
    assert o['account_access_met'] is True
    assert o['legacy_target_met'] is False
    assert o['legacy_shortfall'] == pytest.approx(112_000)
    assert result['success'] is False
    stats=mc(planner(goal=200_000))
    assert stats['outcomes']['planned_spending_met_rate'] == 1
    assert stats['outcomes']['legacy_target_met_rate'] == 0
    assert stats['success_rate'] == 0


def test_positive_legacy_wealth_does_not_hide_early_access_gap():
    result=run(planner(balance=0,restricted=1_000_000,goal=500_000));o=result['outcomes']
    assert not o['planned_spending_met'] and not o['adjusted_spending_met']
    assert o['account_access_met'] is False
    assert o['legacy_target_met'] is True
    assert o['first_funding_shortfall_year'] == 2030
    assert o['first_funding_shortfall_causes'] == ['account_access']
    assert result['final_net_worth'] == 1_000_000
    assert result['success'] is False


def test_access_and_economic_shortfalls_overlap_and_are_not_additive():
    p=planner(balance=0,restricted=5000)
    result=run(p);row=result['projections'][0]
    assert set(row['funding_shortfall_causes']) == {'account_access','liquid_capital'}
    assert row['funding_shortfall'] == 12_000
    stats=mc(p);o=stats['outcomes']
    assert o['first_funding_shortfall_cause_counts'] == {'account_access':3,'liquid_capital':3}
    assert o['first_funding_shortfall_year_counts'] == {'2030':3}
    assert stats['access_failure_rate'] == stats['portfolio_depletion_rate'] == 1
    assert o['adjusted_spending_met_rate'] == 0


def test_funded_adjusted_budget_does_not_claim_original_spending_was_met():
    p=planner(spend=20_000,flexible=True)
    result=run(p);o=result['outcomes'];row=result['projections'][0]
    assert not o['planned_spending_met']
    assert o['adjusted_spending_met']
    assert o['first_spending_cut_year'] == 2030
    assert o['first_funding_shortfall_year'] is None
    assert row['planned_expenses'] == 20_000
    assert row['expenses'] == 18_000
    assert row['funding_shortfall'] == 0
    stats=mc(p)
    assert stats['outcomes']['planned_spending_met_rate'] == 0
    assert stats['outcomes']['adjusted_spending_met_rate'] == 1
    assert stats['spending_cut_frequency'] == 1


def test_exactly_funded_zero_legacy_is_distinct_from_legacy_success_contract():
    result=run(planner(balance=12_000))
    assert result['final_net_worth'] == 0
    assert result['outcomes']['planned_spending_met'] is True
    assert result['outcomes']['legacy_target_met'] is True  # >= target, including zero
    assert result['success'] is False  # historical > target / exhausted balance rule
    assert result['out_of_savings_year'] == 2030
    assert result['outcomes']['first_funding_shortfall_year'] is None


@pytest.mark.parametrize('policy,aggregate',[('unrestricted',False),('penalty_free',True)])
def test_unknown_or_bypassed_access_is_null_with_zero_denominator(policy,aggregate):
    p=planner(policy=policy)
    if aggregate:
        p.input_readiness={'provisional':True,'access_assessed':False,'items':[]}
    result=run(p)
    assert result['outcomes']['account_access_met'] is None
    assert result['projections'][0]['account_access_met'] is None
    assert result['projections'][0]['accessible_spending_balance'] is None
    stats=mc(p)
    assert stats['access_failure_rate'] is None
    assert stats['outcomes']['account_access_met_rate'] is None
    assert stats['outcomes']['denominators'] == {'spending':3,'account_access':0,'legacy':3}


def test_legacy_uses_after_estate_wealth():
    p=planner(balance=30_000_000,spend=0,goal=30_000_000)
    result=run(p)
    assert result['outcomes']['estate_tax'] > 0
    assert result['final_net_worth'] == result['outcomes']['legacy_target']
    assert result['outcomes']['legacy_target_met'] is False
    assert result['outcomes']['legacy_shortfall'] == pytest.approx(result['outcomes']['estate_tax'])
    assert result['outcomes']['estate_tax_timing'] == 'terminal_estimate'
    assert result['estate_tax'] == 0  # historical single-household fields remain unchanged
    assert result['outcomes']['adjusted_spending_met'] is True


@pytest.mark.parametrize('balance,restricted,flexible',[(100_000,0,False),(0,5000,False),(100_000,0,True)])
def test_real_nominal_outcomes_and_shared_annual_rows_agree(balance,restricted,flexible):
    real=run(planner(balance=balance,restricted=restricted,flexible=flexible,last_age=42,goal=50_000))
    nominal=run(planner(balance=balance,restricted=restricted,flexible=flexible,last_age=42,goal=50_000,convention=MonetaryConvention.NOMINAL))
    assert real['outcomes']['legacy_target'] == 50_000
    assert nominal['outcomes']['legacy_target'] == pytest.approx(50_000*1.025**2)
    assert nominal['outcomes']['final_year'] == real['outcomes']['final_year'] == 2032
    for key in ('planned_spending_met','adjusted_spending_met','account_access_met','legacy_target_met','first_funding_shortfall_year','first_funding_shortfall_causes'):
        assert real['outcomes'][key] == nominal['outcomes'][key],key
    for r,n in zip(real['projections'],nominal['projections']):
        factor=1.025**(r['year']-2030)
        assert n['funding_shortfall']/factor == pytest.approx(r['funding_shortfall'],abs=.1)
        assert n['planned_spending_met'] == r['planned_spending_met']
    p=planner(balance=balance,restricted=restricted,flexible=flexible,last_age=42)
    deterministic=p.project_cash_flow();stochastic=run(p)['projections']
    assert [r['adjusted_spending_met'] for r in deterministic] == [r['adjusted_spending_met'] for r in stochastic]


def test_housing_purchase_failure_is_part_of_required_funding():
    event=HousingEvent('buy','Purchase',date(2030,7,1),purchase_price=50_000,funding_account='cash',property_id='home')
    result=run(planner(balance=1000,spend=0,housing=[event]))
    row=result['projections'][0]
    assert row['housing_funding_shortfall'] > 0
    assert result['outcomes']['adjusted_spending_met'] is False
    assert 'housing_purchase' in result['outcomes']['first_funding_shortfall_causes']


def test_reporting_tolerance_is_one_base_year_dollar():
    real=OutcomeTracker(True);nominal=OutcomeTracker(True)
    r=real.observe(2031,.75,0,.75,0,.75,1)
    n=nominal.observe(2031,1.5,0,1.5,0,1.5,2)
    assert r['planned_spending_met'] == n['planned_spending_met'] == True
    assert real.first_spending_cut_year is nominal.first_spending_cut_year is None


def test_reports_preserve_rates_and_definitions_without_inventing_old_outcomes():
    p=planner();stats=mc(p);rows=p.project_cash_flow()
    for report in (generate_mc_report(stats),generate_summary_report(stats,rows)):
        assert report['outcomes'] == stats['outcomes']
    assert 'Adjusted budget funded' in dict(outcome_metric_rows(stats))
    assert generate_mc_report({'success_rate':1})['outcomes'] is None
    assert 'Unavailable' in dict(outcome_metric_rows({'success_rate':1}))['Separate outcomes']


@pytest.mark.parametrize('number',[0,-1,True,1.5])
def test_rate_denominators_require_positive_integer_runs(number):
    with pytest.raises(ValueError,match='positive integer'):
        MonteCarloEngine(planner()).run(num_simulations=number)


def test_married_projection_estate_is_not_subtracted_twice():
    p=planner(balance=60_000_000,spend=0,goal=60_000_000)
    p.scenario.spouse=Person('Partner',date(1990,1,1),date(2030,1,1),40,coverage_type='none')
    r=run(p)
    assert r['estate_tax'] > 0
    assert r['outcomes']['estate_tax_timing'] == 'annual_projection'
    assert r['outcomes']['final_wealth_after_estate'] == pytest.approx(r['final_net_worth']-r['estate_tax'])
    assert r['outcomes']['legacy_shortfall'] == pytest.approx(r['estate_tax'])


def test_cli_and_markdown_reports_use_separate_outcomes(tmp_path):
    from click.testing import CliRunner
    from retirement_planner.cli import main
    cfg={"start_year":2030,"primary":{"name":"Example","birth_date":"1990-01-01","retirement_date":"2030-01-01","longevity_age":40},
         "accounts":[{"id":"b","name":"Cash","type":"checking","balance":100_000,"growth_rate":0,"interest_yield":0,"dividend_yield":0,"capital_gain_yield":0}],
         "expenses":[],"legacy_goal":200_000,"social_security":{"primary_benefit_at_67":0}}
    path=tmp_path/'example.json';path.write_text(json.dumps(cfg))
    for args in (['run','--config',str(path),'--simulations','1'],['report','--config',str(path),'--simulations','1','--format','markdown']):
        result=CliRunner().invoke(main,args)
        assert result.exit_code == 0,result.output
        for label in ('Planned spending met without cuts','Adjusted budget funded','After-estate legacy target met','Combined Success Rate (legacy)'):
            assert label in result.output
        assert 'over-saving' not in result.output


def test_stochastic_run_outcomes_are_plain_json_and_include_terminal_estimate():
    import numpy as np
    p=planner(balance=30_000_000,spend=0,goal=30_000_000,last_age=42)
    result=p.run_single_simulation(return_volatility=.15,rng=np.random.default_rng(7),stochastic=True)
    parsed=json.loads(json.dumps(result['outcomes']))
    assert isinstance(parsed['legacy_target_met'],bool)
    assert parsed['estate_tax_timing'] == 'terminal_estimate'
    assert parsed['estate_tax'] > 0
