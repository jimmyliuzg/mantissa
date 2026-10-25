"""Fictional end-to-end annual contribution and rule-forecast contracts."""
from dataclasses import replace
from datetime import date
import json
import pytest
from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import Account, EconomicAssumptions, IncomeStream, Person, Scenario, MonetaryConvention
from retirement_planner.simulators import MonteCarloEngine


def cash():
    return Account('cash','Cash','checking','taxable',0,growth_rate=0,asset_class='cash')

def account(kind, id='target', owner='primary', priority=1, cap=0):
    tax={'trad_ira':'pre_tax','roth_ira':'roth','401k':'pre_tax','hsa':'tax_exempt'}[kind]
    return Account(id,id,kind,tax,0,growth_rate=0,contribution_priority=priority,annual_contribution_cap=cap,owner=owner)

def planner(accounts, contribution_policy=None, policy=None, inflation=0, nominal=False, age=36, spouse=False, income=100000):
    people = Person('Primary',date(2026-age,1,1),date(2030,1,1),age+2)
    wage=IncomeStream('wage','Wage','primary',income/12,date(2026,1,1),date(2029,1,1))
    return RetirementPlanner(Scenario(name='Fictional rules',description='',primary=people,
        spouse=replace(people,name='Spouse') if spouse else None,
        economic=EconomicAssumptions(general_inflation=inflation),accounts=[*accounts,cash()],
        income_streams=[wage],expenses=[],mortgages=[],start_year=2026,
        contribution_policy=contribution_policy or {},policy=policy,
        monetary_convention=MonetaryConvention.NOMINAL if nominal else MonetaryConvention.REAL))


def facts(**values):
    return {'owners':{'primary':values}}


def test_unconfirmed_ira_and_hsa_do_not_receive_unlimited_surplus():
    for kind in ['trad_ira','hsa']:
        p=planner([account(kind)])
        row=p.project_cash_flow()[0]
        assert row['account_balances']['target']==0
        assert row['account_balances']['cash']>0
        assert p.input_readiness['provisional']
        assert any('require' in message for message in row['model_warnings'])


def test_traditional_ira_deductible_deposit_changes_taxes_and_respects_owner_pool():
    baseline=planner([]).project_cash_flow()[0]
    p=planner([account('trad_ira','ira'),account('roth_ira','roth',priority=2)],
              facts(ira_deduction='deductible',workplace_plan=False))
    row=p.project_cash_flow()[0]
    assert row['contributions']['ira']==7500
    assert row['contributions'].get('roth',0)==0
    assert row['contribution_deductions']=={'ira':7500}
    assert row['taxes']<baseline['taxes']
    assert sum(row['account_balances'].values())==pytest.approx(100000-row['taxes'])


def test_lower_user_ira_cap_and_roth_share_one_owner_ceiling():
    row=planner([account('trad_ira','ira',cap=5000),account('roth_ira','roth',priority=2)],
                facts(ira_deduction='deductible',workplace_plan=False)).project_cash_flow()[0]
    assert row['contributions']['ira']==5000
    assert row['contributions']['roth']==2500


def test_traditional_and_roth_ira_pooling_respects_priority_and_partial_roth_phaseout():
    assumptions=facts(ira_deduction='deductible',workplace_plan=False)
    traditional_first=planner([
        account('trad_ira','traditional',priority=1,cap=5000),
        account('roth_ira','roth',priority=2),
    ], assumptions, income=160500).project_cash_flow()[0]
    assert traditional_first['contributions']['traditional']==5000
    assert traditional_first['contributions']['roth']==2500

    roth_first=planner([
        account('roth_ira','roth',priority=1),
        account('trad_ira','traditional',priority=2,cap=5000),
    ], assumptions, income=160500).project_cash_flow()[0]
    assert roth_first['contributions']['roth']==3750
    assert roth_first['contributions']['traditional']==3750


def test_roth_phaseout_uses_magi_after_workplace_deferral():
    # Gross wages exceed the single Roth phaseout end, but a workplace
    # deferral brings the relevant MAGI below its beginning.
    row=planner([account('401k','k'),account('roth_ira','r',priority=2)],income=175000).project_cash_flow()[0]
    assert row['contributions']['k']==24500
    assert row['contributions']['r']==7500
    high=planner([account('roth_ira')],income=400000).project_cash_flow()[0]
    assert high['contributions'].get('target',0)==0


def test_hsa_employer_deposit_is_credited_once_and_reduces_employee_cap():
    p=planner([account('hsa')],facts(hsa_eligible=True,hsa_coverage='individual',hsa_employer_contribution_by_year={'2026':1000}))
    row=p.project_cash_flow()[0]
    assert row['contributions']['target']==3400
    assert row['employer_hsa_contributions']=={'target':1000}
    assert row['account_balances']['target']==4400
    assert sum(row['account_balances'].values())==pytest.approx(101000-row['taxes'])
    again=p.project_cash_flow()[0]
    assert again['account_balances']==row['account_balances']


def test_declared_employer_hsa_above_ceiling_is_rejected():
    p=planner([account('hsa')],facts(hsa_eligible=True,hsa_coverage='individual',hsa_employer_contribution_by_year={'2026':9000}))
    with pytest.raises(ValueError,match='exceeds eligible annual limit'):
        p.project_cash_flow()


@pytest.mark.parametrize('kind',['trad_ira','roth_ira','hsa','brokerage'])
def test_direct_scenario_rejects_employer_match_outside_workplace_accounts(kind):
    invalid=account(kind) if kind!='brokerage' else Account('target','target','brokerage','taxable',0,growth_rate=0,contribution_priority=1)
    invalid.employer_match=.5
    invalid.employer_match_limit=1000
    with pytest.raises(ValueError,match='employer_match requires a workplace retirement account'):
        planner([invalid])


def test_hsa_family_shared_caps_and_catchup_proration():
    owner={'hsa_eligible':True,'hsa_coverage':'family'}
    p=planner([account('hsa','a'),account('hsa','b',owner='spouse',priority=2)],
        {'owners':{'primary':owner,'spouse':owner}},spouse=True)
    row=p.project_cash_flow()[0]
    assert sum(row['contributions'].values())==8750
    partial=planner([account('hsa')],facts(hsa_eligible=True,hsa_coverage='individual',hsa_eligible_months=6),age=55).project_cash_flow()[0]
    assert partial['contributions']['target']==2700


def test_published_partial_year_hsa_and_temporary_forecast_reversion():
    policy={'schema_version':1,'changes':[{'id':'temporary hsa','start_year':2027,'end_year':2027,'contributions':{'hsa_individual':6000}}]}
    p=planner([account('hsa')],facts(hsa_eligible=True,hsa_coverage='individual'),policy)
    rows=p.project_cash_flow()
    assert [r['contributions']['target'] for r in rows]==[4400,6000,4500]
    assert rows[1]['rule_assumptions']['contributions']['fields']['hsa_individual']['status']=='user'
    assert rows[1]['rule_assumptions']['tax']['status']=='projected'


def test_tax_forecast_temporary_rates_change_actual_taxes_then_revert():
    baseline=planner([]).project_cash_flow()
    policy={'schema_version':1,'changes':[{'id':'higher tax','start_year':2027,'end_year':2027,'tax':{'federal_rate_multiplier':1.1}}]}
    rows=planner([],policy=policy).project_cash_flow()
    assert rows[0]['taxes']==baseline[0]['taxes']
    assert rows[1]['taxes']>baseline[1]['taxes']
    assert rows[2]['taxes']==baseline[2]['taxes']
    assert rows[1]['rule_assumptions']['applied_change_ids']==['higher tax']
    assert rows[2]['rule_assumptions']['applied_change_ids']==[]


def test_real_and_nominal_contribution_ceilings_agree_in_nominal_dollars():
    args=facts(hsa_eligible=True,hsa_coverage='individual')
    real=planner([account('hsa')],args,inflation=.025).project_cash_flow()
    nominal=planner([account('hsa')],args,inflation=.025,nominal=True).project_cash_flow()
    for i,(a,b) in enumerate(zip(real,nominal)):
        assert a['contributions']['target']*1.025**i==pytest.approx(b['contributions']['target'])


def test_config_policies_roundtrip_and_fingerprint_without_value_leak(tmp_path):
    cfg={'name':'Fictional','start_year':2026,'primary':{'name':'P','birth_date':'1990-01-01','retirement_date':'2030-01-01','longevity_age':38},
         'accounts':[], 'policy':{'schema_version':1,'changes':[{'start_year':2027,'tax':{'federal_rate_addition':.01}}]},
         'contribution_policy':facts(hsa_eligible=True,hsa_coverage='individual')}
    path=tmp_path/'plan.json';path.write_text(json.dumps(cfg))
    p=RetirementPlanner.from_config(str(path))
    assert p.scenario.policy==cfg['policy']
    assert p.scenario.contribution_policy==cfg['contribution_policy']
    result=MonteCarloEngine(p).run(num_simulations=1,seed=17)
    assert result['run_metadata']['config_fingerprint']==p.config_fingerprint()
    assert result['run_metadata']['effective_seed']==17
