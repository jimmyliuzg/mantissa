"""Fixtures are also checked against buildSlimConfig by the browser test suite."""
import json
from pathlib import Path

import pytest

from retirement_planner.config.validation import validate_config
from retirement_planner.engine import RetirementPlanner

FIXTURES=json.loads((Path(__file__).parents[1]/'fixtures/wizard-contract.json').read_text())


@pytest.fixture
def planners(tmp_path):
    result={}
    for item in FIXTURES:
        cfg=item['config']
        validate_config(cfg,strict=True).raise_for_errors()
        file=tmp_path/(item['name']+'.json');file.write_text(json.dumps(cfg))
        result[item['name']]=RetirementPlanner.from_config(str(file))
    return result


def test_all_wizard_variants_parse_and_run_in_native_engine(planners):
    for p in planners.values():
        rows=p.project_cash_flow()
        assert rows
        assert all(abs(sum(r['expenses_by_category'].values())-r['expenses']) < .1 for r in rows)
        assert p.scenario.legacy_goal == 0
        assert p.input_readiness['provisional']


def test_risk_changes_actual_allocation_and_returns(planners):
    low,high=planners['low'],planners['high']
    assert low._account_allocation(low.accounts['brokerage'],2031).equity_pct < high._account_allocation(high.accounts['brokerage'],2031).equity_pct
    assert low._account_growth_rate(low.accounts['brokerage'],2031,low.scenario.economic.get_rate('mean')) < high._account_growth_rate(high.accounts['brokerage'],2031,high.scenario.economic.get_rate('mean'))
    assert low.accounts['brokerage'].growth_rate is None


def test_skipped_ss_is_zero_at_claiming_age_and_salary_is_full_year(planners):
    p=planners['low']
    assert p.calculate_social_security(2033,p.scenario.primary) == 0
    default=planners['aggregate']
    assert default.calculate_annual_income(2031)['total'] == pytest.approx(120_000)
    assert not default.input_readiness['access_assessed']
    assert planners['low'].input_readiness['access_assessed']
    assert planners['high'].accounts['brokerage'].cost_basis == 150_000


def test_cash_profile_total_return_includes_interest(planners):
    p=planners['low']
    cash=p.accounts['cash']
    assert cash.interest_yield == .03
    assert (1 + cash.growth_rate)*1.025 == pytest.approx(1.03)
