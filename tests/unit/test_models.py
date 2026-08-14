"""Tests for the data models (models.py)."""
import json
from datetime import date

import pytest

from retirement_planner.models import (
    Account, AssetAllocation, EconomicAssumptions, IncomeStream, Person,
    Scenario, SocialSecurity,
    RSUGrant, RefresherPolicy, Bonus, EquityComp,
)


# ---------------------------------------------------------------------------
# AssetAllocation validation
# ---------------------------------------------------------------------------
def test_asset_allocation_valid():
    alloc = AssetAllocation(equity_pct=0.6, bond_pct=0.4)
    assert alloc.equity_pct == 0.6
    assert alloc.bond_pct == 0.4


def test_asset_allocation_full_equity():
    alloc = AssetAllocation(equity_pct=1.0, bond_pct=0.0)
    assert alloc.equity_pct == 1.0


def test_asset_allocation_negative_raises():
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        AssetAllocation(equity_pct=-0.1, bond_pct=1.1)


def test_asset_allocation_above_one_raises():
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        AssetAllocation(equity_pct=1.2, bond_pct=-0.2)


def test_asset_allocation_bad_sum_raises():
    with pytest.raises(ValueError, match="sum to 1.0"):
        AssetAllocation(equity_pct=0.5, bond_pct=0.4)


def test_asset_allocation_sum_drift_tolerance():
    # Tiny floating-point drift within 0.01 tolerance is allowed
    alloc = AssetAllocation(equity_pct=0.333, bond_pct=0.666)
    assert abs(alloc.equity_pct + alloc.bond_pct - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Person / Account / IncomeStream dataclasses
# ---------------------------------------------------------------------------
def test_person_creation():
    p = Person(
        name="Alice",
        birth_date=date(1970, 5, 15),
        retirement_date=date(2035, 1, 1),
        longevity_age=95,
        social_security_benefit=2800.0,
        ss_claiming_age=70,
    )
    assert p.name == "Alice"
    assert p.birth_date == date(1970, 5, 15)
    assert p.longevity_age == 95
    assert p.ss_claiming_age == 70


def test_person_defaults():
    p = Person(
        name="Bob",
        birth_date=date(1980, 1, 1),
        retirement_date=date(2045, 1, 1),
    )
    assert p.longevity_age == 90
    assert p.social_security_benefit == 0.0
    assert p.ss_claiming_age == 67


def test_account_creation_and_defaults():
    acct = Account(
        id="401k_primary",
        name="401k - Primary",
        account_type="401k",
        tax_treatment="pre_tax",
        balance=150_000,
    )
    assert acct.id == "401k_primary"
    assert acct.balance == 150_000
    assert acct.growth_rate is None  # None = use CMA returns
    assert acct.monthly_contribution == 0.0
    assert acct.liquid is True
    assert acct.expense_ratio == 0.0


def test_account_project_balance():
    acct = Account(
        id="brokerage", name="Brokerage", account_type="brokerage",
        tax_treatment="taxable", balance=100_000,
    )
    expected = 100_000 * (1.07 ** 10)
    assert acct.project_balance(10, 0.07) == pytest.approx(expected)
    assert acct.project_balance(0, 0.07) == 100_000


def test_income_stream_creation():
    stream = IncomeStream(
        id="salary",
        name="Salary - Primary",
        owner="primary",
        monthly_amount=10_000,
        start_date=date(2024, 1, 1),
        end_date=date(2030, 1, 1),
        growth_rate=0.03,
    )
    assert stream.monthly_amount == 10_000
    assert stream.is_w2 is True
    assert stream.is_ss is False
    assert stream.growth_rate == 0.03


# ---------------------------------------------------------------------------
# Scenario.to_dict() round-trip
# ---------------------------------------------------------------------------
def _make_scenario() -> Scenario:
    primary = Person(
        name="Primary", birth_date=date(1970, 1, 1),
        retirement_date=date(2035, 1, 1), longevity_age=92,
    )
    spouse = Person(
        name="Spouse", birth_date=date(1972, 6, 15),
        retirement_date=date(2037, 1, 1), longevity_age=94,
    )
    return Scenario(
        name="Test Scenario",
        description="Round-trip test",
        primary=primary,
        spouse=spouse,
        economic=EconomicAssumptions(),
        accounts=[],
        income_streams=[],
        expenses=[],
        mortgages=[],
        social_security=SocialSecurity(),
        legacy_goal=1_500_000,
        state="CA",
    )


def test_scenario_to_dict_fields():
    sc = _make_scenario()
    d = sc.to_dict()

    assert d["name"] == "Test Scenario"
    assert d["description"] == "Round-trip test"
    assert d["legacy_goal"] == 1_500_000
    assert d["state"] == "CA"

    assert d["primary"]["name"] == "Primary"
    assert d["primary"]["birth_date"] == "1970-01-01"
    assert d["primary"]["retirement_date"] == "2035-01-01"
    assert d["primary"]["longevity_age"] == 92

    assert d["spouse"]["name"] == "Spouse"
    assert d["spouse"]["birth_date"] == "1972-06-15"
    assert d["spouse"]["longevity_age"] == 94


def test_scenario_to_dict_deserialize_matches():
    sc = _make_scenario()
    d = sc.to_dict()

    # Deserialize fields back and verify they match the original objects
    assert date.fromisoformat(d["primary"]["birth_date"]) == sc.primary.birth_date
    assert date.fromisoformat(d["primary"]["retirement_date"]) == sc.primary.retirement_date
    assert date.fromisoformat(d["spouse"]["birth_date"]) == sc.spouse.birth_date
    assert d["name"] == sc.name
    assert d["legacy_goal"] == sc.legacy_goal


def test_scenario_to_json_round_trip():
    sc = _make_scenario()
    parsed = json.loads(sc.to_json())
    assert parsed == sc.to_dict()
    assert parsed["primary"]["name"] == "Primary"


# ---------------------------------------------------------------------------
# RSUGrant model
# ---------------------------------------------------------------------------
def test_rsu_grant_creation():
    grant = RSUGrant(
        id="grant_1",
        grant_date=date(2025, 10, 10),
        total_shares=2000,
        vesting_pattern="cliff_quarterly",
        cliff_shares=1000,
        periodic_shares=250,
        cliff_date=date(2026, 10, 10),
    )
    assert grant.cliff_replaces_first_vest is False
    assert grant.status == "active"


def test_rsu_grant_defaults():
    grant = RSUGrant(
        id="grant_2",
        grant_date=date(2025, 8, 10),
        total_shares=230,
        vesting_pattern="quarterly",
        periodic_shares=57,
    )
    assert grant.cliff_shares == 0
    assert grant.cliff_date is None
    assert grant.cliff_replaces_first_vest is False


# ---------------------------------------------------------------------------
# RefresherPolicy model
# ---------------------------------------------------------------------------
def test_refresher_policy_creation():
    policy = RefresherPolicy(
        annual_shares=250,
        grant_month=10,
        vesting_pattern="quarterly",
        vesting_delay_months=3,
        start_year=2026,
        end_year=2035,
        growth_rate=0.0,
    )
    assert policy.annual_shares == 250
    assert policy.vesting_delay_months == 3


def test_refresher_policy_defaults():
    policy = RefresherPolicy(annual_shares=100, grant_month=6, vesting_pattern="monthly")
    assert policy.vesting_delay_months == 3
    assert policy.growth_rate == 0.0
    assert policy.start_year == 0
    assert policy.end_year == 0


# ---------------------------------------------------------------------------
# Bonus model
# ---------------------------------------------------------------------------
def test_bonus_creation():
    bonus = Bonus(annual=18000, growth_rate=0.03, payment_month=3)
    assert bonus.annual == 18000
    assert bonus.payment_month == 3


def test_bonus_defaults():
    bonus = Bonus()
    assert bonus.annual == 0.0
    assert bonus.growth_rate == 0.0
    assert bonus.payment_month == 3


# ---------------------------------------------------------------------------
# EquityComp model
# ---------------------------------------------------------------------------
def test_equity_comp_creation():
    equity = EquityComp(
        ticker="EXMP",
        current_price=50.0,
        grants=[
            RSUGrant(
                id="grant_1",
                grant_date=date(2025, 10, 10),
                total_shares=2000,
                vesting_pattern="cliff_quarterly",
                cliff_shares=1000,
                periodic_shares=250,
                cliff_date=date(2026, 10, 10),
            ),
        ],
        refreshers=RefresherPolicy(
            annual_shares=250,
            grant_month=10,
            vesting_pattern="quarterly",
            start_year=2026,
            end_year=2035,
        ),
        sell_to_cover=True,
        goes_to_account="brokerage_spouse",
    )
    assert equity.ticker == "EXMP"
    assert len(equity.grants) == 1
    assert equity.refreshers is not None
    assert equity.sell_to_cover is True
    assert equity.is_taxable is True
    assert equity.end_date is None


def test_equity_comp_defaults():
    equity = EquityComp()
    assert equity.ticker == ""
    assert equity.current_price == 0.0
    assert equity.grants == []
    assert equity.refreshers is None
    assert equity.sell_to_cover is True


# ---------------------------------------------------------------------------
# IncomeStream with enhanced comp fields
# ---------------------------------------------------------------------------
def test_income_stream_legacy_compatibility():
    """Legacy IncomeStream with only monthly_amount still works."""
    stream = IncomeStream(
        id="salary",
        name="Salary",
        owner="primary",
        monthly_amount=10000,
        start_date=date(2026, 1, 1),
        end_date=date(2035, 1, 1),
    )
    assert stream.monthly_amount == 10000
    assert stream.base_salary is None
    assert stream.bonus is None
    assert stream.equity is None


def test_income_stream_with_base_salary():
    stream = IncomeStream(
        id="spouse_globex",
        name="Spouse — Globex",
        owner="spouse",
        monthly_amount=0,
        start_date=date(2026, 1, 1),
        end_date=date(2036, 1, 1),
        base_salary={"annual": 180000, "growth_rate": 0.03},
        bonus=Bonus(annual=18000, growth_rate=0.03, payment_month=3),
        equity=EquityComp(ticker="EXMP", current_price=50.0),
    )
    assert stream.base_salary is not None
    assert stream.bonus is not None
    assert stream.equity is not None
    assert stream.base_salary["annual"] == 180000
    assert stream.bonus.annual == 18000
    assert stream.equity.ticker == "EXMP"
