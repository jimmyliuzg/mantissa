"""Regression coverage for website planner controls.

The website exposes an optional destination for post-contribution surplus and
surfaces model limitations as warnings. These checks keep the config parser,
engine validation, and warning copy in sync with those controls.
"""
import json
from datetime import date

import pytest

from retirement_planner.config.validation import validate_config
from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import (
    Account,
    EconomicAssumptions,
    IncomeStream,
    Person,
    Scenario,
)


def _config(accounts, **extra):
    return {
        "name": "Website control regression",
        "start_year": 2026,
        "primary": {
            "name": "A",
            "birth_date": "1990-01-01",
            "retirement_date": "2030-01-01",
            "longevity_age": 90,
        },
        "accounts": accounts,
        "income_streams": [{
            "id": "salary",
            "name": "Salary",
            "owner": "primary",
            "monthly_amount": 10_000,
            "start_date": "2026-01-01",
            "end_date": "2030-01-01",
        }],
        "economic": {"general_inflation": 0},
        **extra,
    }


def _direct_scenario(accounts, surplus_account_id=None, state="CA"):
    return Scenario(
        name="Website control regression",
        description="",
        start_year=2026,
        primary=Person("A", date(1990, 1, 1), date(2030, 1, 1), 90),
        spouse=None,
        economic=EconomicAssumptions(general_inflation=0),
        accounts=accounts,
        income_streams=[IncomeStream(
            "salary", "Salary", "primary", 10_000,
            date(2026, 1, 1), date(2030, 1, 1),
        )],
        expenses=[],
        mortgages=[],
        surplus_account_id=surplus_account_id,
        state=state,
    )


def _destination_accounts():
    return [
        {"id": "checking", "name": "Checking", "type": "checking",
         "tax_treatment": "taxable", "balance": 0, "growth_rate": 0},
        {"id": "brokerage", "name": "Brokerage", "type": "brokerage",
         "tax_treatment": "taxable", "balance": 0, "growth_rate": 0},
        {"id": "401k", "name": "401(k)", "type": "401k",
         "tax_treatment": "pre_tax", "balance": 0, "growth_rate": 0,
         "contribution_priority": 1, "annual_contribution_cap": 20_000},
    ]


def test_explicit_surplus_destination_gets_post_contribution_cash(tmp_path):
    cfg = _config(_destination_accounts(), surplus_account_id="brokerage")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(cfg))

    planner = RetirementPlanner.from_config(str(path))
    row = planner.project_cash_flow()[0]

    assert planner.scenario.surplus_account_id == "brokerage"
    assert row["contributions"]["401k"] > 0
    assert row["account_balances"]["brokerage"] == pytest.approx(
        row["net_cash_flow"] - sum(row["contributions"].values())
    )
    assert row["account_balances"]["checking"] == 0


def test_default_surplus_destination_remains_checking(tmp_path):
    cfg = _config(_destination_accounts())
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(cfg))
    result = RetirementPlanner.from_config(str(path)).project_cash_flow()[0]

    assert result["account_balances"]["checking"] == pytest.approx(
        result["net_cash_flow"] - sum(result["contributions"].values())
    )
    assert result["account_balances"]["brokerage"] == 0


@pytest.mark.parametrize("destination", [
    "missing",
    "401k",
    "home",
])
def test_invalid_surplus_destination_rejected_by_config_and_engine(destination, tmp_path):
    accounts = _destination_accounts()
    if destination == "home":
        accounts.append({"id": "home", "name": "Home", "type": "real_estate",
                         "tax_treatment": "taxable", "balance": 100_000,
                         "liquid": False})
    cfg = _config(accounts, surplus_account_id=destination)

    assert not validate_config(cfg).valid
    path = tmp_path / "invalid-plan.json"
    path.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="surplus_account_id"):
        RetirementPlanner.from_config(str(path))

    direct_accounts = [
        Account("cash", "Cash", "checking", "taxable", 0, growth_rate=0),
    ]
    if destination == "401k":
        direct_accounts.append(Account("401k", "401(k)", "401k", "pre_tax", 0))
    elif destination == "home":
        direct_accounts.append(Account("home", "Home", "real_estate", "taxable", 100_000, liquid=False))
    with pytest.raises(ValueError, match="surplus_account_id"):
        RetirementPlanner(_direct_scenario(direct_accounts, destination))


def test_config_parser_preserves_surplus_account_id(tmp_path):
    cfg = _config(_destination_accounts(), surplus_account_id="brokerage")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(cfg))

    planner = RetirementPlanner.from_config(str(path))

    assert planner.scenario.surplus_account_id == "brokerage"


def test_non_california_warning_names_omitted_state_income_tax_only():
    planner = RetirementPlanner(_direct_scenario([], state="WA"))

    assert any("State income tax is modeled only for California" in warning
               and "omits state income tax" in warning
               for warning in planner.model_warnings)
    assert not any("investment distributions are not modeled" in warning.lower()
                   for warning in planner.model_warnings)
    assert any("Investment distributions use declared yields" in warning
               for warning in planner.model_warnings)


def test_california_has_no_unsupported_state_tax_warning():
    planner = RetirementPlanner(_direct_scenario([], state="CA"))

    assert not any("State income tax is modeled only for California" in warning
                   for warning in planner.model_warnings)
