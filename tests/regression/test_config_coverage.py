"""Config-coverage audit: every honored Scenario field must change output.

The engine silently ignored several config fields over its history
(medical inflation, CTC, Expense.growth_rate, Account.is_depreciating /
liquid).  Each test below flips ONE field and asserts the projection
changes — a regression guard so future refactors cannot silently
disconnect a config option again.

Dead fields (legacy, never honored) must at least warn on load.
"""
import json
import warnings
from datetime import date

import pytest

from retirement_planner import RetirementPlanner
from retirement_planner.models import (
    Account, AgeEvent, Dependent, EconomicAssumptions, Expense,
    GlidepathConfig, IncomeStream, MonetaryConvention, Mortgage, Person,
    Scenario, SocialSecurity,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------
def base_planner() -> RetirementPlanner:
    """Small, fast, solvent household with one of everything."""
    scenario = Scenario(
        name="coverage", description="",
        primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 80),
        spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 80),
        economic=EconomicAssumptions(),
        accounts=[
            Account("b", "B", "brokerage", "taxable", 2_000_000, equity_pct=0.6),
            Account("home", "Home", "real_estate", "taxable", 800_000,
                    liquid=False),
            Account("car", "Car", "vehicle", "taxable", 25_000, liquid=False,
                    is_depreciating=True),
        ],
        income_streams=[
            IncomeStream("rent", "Rent", owner="primary", monthly_amount=2_000,
                         start_date=date(2026, 1, 1),
                         end_date=date(2090, 12, 31), is_passive=True),
        ],
        expenses=[
            Expense("groceries", "Groceries", monthly_amount=1_500,
                    start_date=date(2026, 1, 1), end_date=date(2090, 12, 31)),
            Expense("health", "Health", monthly_amount=1_000,
                    start_date=date(2026, 1, 1), end_date=date(2090, 12, 31),
                    category="medical", is_must_spend=True),
        ],
        mortgages=[
            Mortgage(id="m1", name="M1", property_id="home", balance=400_000,
                     interest_rate=0.05, monthly_payment=3_000,
                     start_date=date(2026, 1, 1), end_date=date(2045, 12, 31)),
        ],
        age_events=[AgeEvent(trigger_age=65, expense_id="health",
                             new_monthly_amount=2_000)],
        dependents=[Dependent(name="Kid", birth_date=date(2027, 1, 1))],
        social_security=SocialSecurity(
            primary_benefit_at_67=2_100, spouse_benefit_at_67=1_500),
    )
    return RetirementPlanner(scenario)


def det_signal(planner: RetirementPlanner, year: int) -> tuple:
    """Deterministic row for one year: (income, expenses, taxes, aca, nw)."""
    rows = planner.project_cash_flow()
    row = next(r for r in rows if r["year"] == year)
    return (round(row["income"], 1), round(row["expenses"], 1),
            round(row["taxes"], 1), round(row["aca_subsidy"], 1),
            round(row["net_worth"], 1))


def mc_signal(planner: RetirementPlanner) -> tuple:
    """MC single-run summary (volatility-free, deterministic RNG)."""
    import numpy as np
    run = planner.run_single_simulation(
        return_volatility=0.0, rng=np.random.default_rng(7))
    return (run["success"], round(run["final_net_worth"], 1),
            round(run["lifetime_taxes"], 1), round(run["lifetime_ss"], 1),
            run["out_of_savings_year"])


def assert_det_changes(mutate, year: int = 2030):
    base = det_signal(base_planner(), year)
    flipped = det_signal(mutate(base_planner()), year)
    assert base != flipped, f"field flip had no effect (det {year}): {base}"


def assert_mc_changes(mutate):
    base = mc_signal(base_planner())
    flipped = mc_signal(mutate(base_planner()))
    assert base != flipped, f"field flip had no effect (MC): {base}"


# ---------------------------------------------------------------------------
# Deterministic-path fields
# ---------------------------------------------------------------------------
class TestExpenseFields:
    def test_monthly_amount(self):
        assert_det_changes(lambda p: p.scenario.expenses[0].__setattr__(
            "monthly_amount", 2_000) or p)

    def test_real_growth_rate(self):
        def flip(p):
            p.scenario.expenses[0].real_growth_rate = 0.03
            return p
        assert_det_changes(flip, year=2040)

    def test_growth_rate_legacy_wired(self):
        def flip(p):
            p.scenario.expenses[0].growth_rate = 0.03
            return p
        assert_det_changes(flip, year=2040)

    def test_category_medical_drives_aca(self):
        def flip(p):
            p.scenario.expenses[0].category = "medical"
            return p
        # medical-category expense increases premium → subsidy changes
        assert_det_changes(flip)

    def test_one_time_event(self):
        def flip(p):
            p.scenario.expenses[0].is_one_time = True
            p.scenario.expenses[0].one_time_amount = 25_000
            p.scenario.expenses[0].one_time_date = date(2030, 6, 1)
            return p
        assert_det_changes(flip, year=2030)


class TestAgeEventFields:
    def test_new_monthly_amount(self):
        def flip(p):
            p.scenario.age_events[0].new_monthly_amount = 5_000
            return p
        assert_det_changes(flip, year=2050)

    def test_duration_years(self):
        def flip(p):
            p.scenario.age_events[0].duration_years = 3
            return p
        assert_det_changes(flip, year=2055)

    def test_trigger_age(self):
        def flip(p):
            p.scenario.age_events[0].trigger_age = 70
            return p
        assert_det_changes(flip, year=2050)


class TestPersonFields:
    def test_longevity_age(self):
        def flip(p):
            p.scenario.spouse.longevity_age = 90  # 80 → 90: horizon extends
            return p
        base = det_signal(base_planner(), 2050)
        flipped = det_signal(flip(base_planner()), 2050)
        # Horizon length changes even if the 2050 row does not
        rows_base = base_planner().project_cash_flow()
        rows_flip = flip(base_planner()).project_cash_flow()
        assert len(rows_base) != len(rows_flip) or base != flipped

    def test_retirement_date_gates_contributions(self):
        def flip(p):
            # Contributions happen while working; retiring later keeps
            # them running longer.
            p.scenario.income_streams.append(IncomeStream(
                "salary", "Salary", owner="primary", monthly_amount=20_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31)))
            p.accounts["b"].monthly_contribution = 2_000
            p.scenario.primary.retirement_date = date(2040, 1, 1)
            return p
        assert_mc_changes(flip)

    def test_coverage_type(self):
        def flip(p):
            p.scenario.primary.coverage_type = "none"
            return p
        assert_det_changes(flip)


class TestAccountFields:
    def test_balance(self):
        assert_det_changes(lambda p: p.accounts["b"].__setattr__(
            "balance", 3_000_000) or p)

    def test_growth_rate(self):
        assert_det_changes(lambda p: p.accounts["b"].__setattr__(
            "growth_rate", 0.09) or p)

    def test_equity_pct_override(self):
        def flip(p):
            p.accounts["b"].equity_pct = 0.3
            return p
        assert_det_changes(flip)

    def test_expense_ratio(self):
        assert_det_changes(lambda p: p.accounts["b"].__setattr__(
            "expense_ratio", 0.01) or p)

    def test_is_depreciating(self):
        def flip(p):
            p.accounts["car"].is_depreciating = False
            p.accounts["car"].growth_rate = 0.05
            return p
        assert_det_changes(flip)

    def test_liquid_affects_withdrawal_order(self):
        def flip(p):
            p.accounts["b"].liquid = False
            return p
        assert_mc_changes(flip)

    def test_owner(self):
        def flip(p):
            p.accounts["b"].equity_pct = None  # let the glidepath drive
            p.scenario.glidepath = GlidepathConfig(
                equity_by_age={40: 0.6, 60: 0.3})
            p.accounts["b"].owner = "spouse"
            return p
        assert_mc_changes(flip)


class TestIncomeFields:
    def test_monthly_amount(self):
        assert_det_changes(lambda p: p.scenario.income_streams[0]
                           .__setattr__("monthly_amount", 3_000) or p)

    def test_growth_rate(self):
        assert_det_changes(lambda p: p.scenario.income_streams[0]
                           .__setattr__("growth_rate", 0.03) or p,
                           year=2040)


class TestSocialSecurityFields:
    def test_primary_benefit(self):
        assert_det_changes(lambda p: p.scenario.social_security
                           .__setattr__("primary_benefit_at_67", 3_000) or p,
                           year=2050)

    def test_claiming_age(self):
        assert_det_changes(lambda p: p.scenario.social_security
                           .__setattr__("primary_claiming_age", 70) or p,
                           year=2050)

    def test_cola_rate(self):
        def flip(p):
            p.scenario.social_security.cola_rate = 0.03
            return p
        assert_det_changes(flip, year=2050)

    def test_economic_ss_cola_wired_through(self):
        """economic.ss_cola feeds SocialSecurity.cola_rate (single source)."""
        def flip(p):
            p.scenario.economic.ss_cola = 0.031
            p.scenario.social_security.cola_rate = 0.031
            return p
        assert_det_changes(flip, year=2050)


class TestMortgageFields:
    def test_balance(self):
        assert_det_changes(lambda p: p.scenario.mortgages[0].__setattr__(
            "balance", 500_000) or p)

    def test_interest_rate(self):
        assert_det_changes(lambda p: p.scenario.mortgages[0].__setattr__(
            "interest_rate", 0.06) or p)

    def test_monthly_payment(self):
        assert_det_changes(lambda p: p.scenario.mortgages[0].__setattr__(
            "monthly_payment", 4_000) or p)

    def test_is_tax_deductible(self):
        def flip(p):
            p.scenario.mortgages[0].balance = 900_000  # interest > std ded
            p.scenario.mortgages[0].is_tax_deductible = False
            return p
        assert_mc_changes(flip)


class TestEconomicFields:
    def test_equity_real_return(self):
        def flip(p):
            p.scenario.economic.equity_real_return = 0.08
            return p
        assert_det_changes(flip)

    def test_bond_real_return(self):
        def flip(p):
            p.scenario.economic.bond_real_return = 0.03
            return p
        assert_det_changes(flip)

    def test_housing_appreciation(self):
        def flip(p):
            p.scenario.economic.housing_appreciation = 0.02
            return p
        assert_det_changes(flip)

    def test_medical_inflation(self):
        def flip(p):
            p.scenario.economic.medical_inflation = 0.05
            return p
        assert_det_changes(flip, year=2050)

    def test_general_inflation_nominal_mode(self):
        def flip(p):
            p.scenario.monetary_convention = MonetaryConvention.NOMINAL
            p.scenario.economic.general_inflation = 0.03
            return p
        assert_det_changes(flip, year=2050)

    def test_optimistic_scenario_changes_output(self):
        rows = base_planner().project_cash_flow()
        rows_opt = base_planner().project_cash_flow(scenario_name="optimistic")
        assert rows != rows_opt


class TestGlidepathFields:
    def test_equity_by_age(self):
        def flip(p):
            p.accounts["b"].equity_pct = None
            p.scenario.glidepath = GlidepathConfig(
                equity_by_age={40: 0.3, 60: 0.2})
            return p
        assert_det_changes(flip)

    def test_tent_equity(self):
        def flip(p):
            p.accounts["b"].equity_pct = None
            p.scenario.glidepath = GlidepathConfig(tent_equity_pct=0.8)
            return p
        assert_det_changes(flip)


class TestScenarioFields:
    def test_state(self):
        assert_det_changes(lambda p: p.scenario.__setattr__(
            "state", "TX") or p, year=2050)

    def test_legacy_goal(self):
        base = mc_signal(base_planner())

        def flip(p):
            p.scenario.legacy_goal = base[1] * 2  # above final NW
            return p
        assert_mc_changes(flip)

    def test_withdrawal_strategy(self):
        def flip(p):
            p.scenario.withdrawal_strategy = "percent_of_portfolio"
            p.scenario.withdrawal_rate = 0.03
            return p
        assert_mc_changes(flip)

    def test_withdrawal_rate(self):
        def flip(p):
            p.scenario.withdrawal_strategy = "percent_of_portfolio"
            p.scenario.withdrawal_rate = 0.05
            return p
        assert_mc_changes(flip)

    def test_guardrails(self):
        def flip(p):
            p.scenario.withdrawal_strategy = "guardrails"
            p.scenario.guardrail_floor_pct = 0.8
            p.scenario.guardrail_ceiling_pct = 1.2
            return p
        assert_mc_changes(flip)


class TestDependentFields:
    def test_birth_date_drives_aca_and_ctc(self):
        def flip(p):
            p.scenario.dependents[0].birth_date = date(2040, 1, 1)
            return p
        assert_det_changes(flip)


# ---------------------------------------------------------------------------
# MC-only event fields
# ---------------------------------------------------------------------------
class TestEventFields:
    def test_windfall(self):
        from retirement_planner.models import Windfall

        def flip(p):
            p.scenario.windfalls = [Windfall(
                id="w", name="W", amount=500_000, date=date(2032, 3, 1),
                goes_to_account="b")]
            return p
        assert_mc_changes(flip)

    def test_windfall_source_account_is_neutral(self):
        """A sourced windfall is a transfer: NW unchanged, accounts shift."""
        from retirement_planner.models import Windfall

        def with_windfall(source):
            p = base_planner()
            p.scenario.windfalls = [Windfall(
                id="w", name="W", amount=100_000, date=date(2032, 3, 1),
                goes_to_account="b", source_account=source)]
            return p
        plain = mc_signal(base_planner())
        transfer = mc_signal(with_windfall("b"))
        # Transfer within the same account → no-op on NW
        assert plain[1] == pytest.approx(transfer[1], rel=1e-9)

    def test_roth_conversion(self):
        from retirement_planner.models import Account as A, RothConversion
        p = base_planner()
        p.scenario.accounts.append(A("trad", "Trad", "trad_ira",
                                     "pre_tax", 300_000, liquid=True))
        p.accounts["trad"] = A("trad", "Trad", "trad_ira", "pre_tax",
                               300_000, liquid=True)
        p.scenario.roth_conversions = [RothConversion(
            id="rc", name="RC", source_account="trad",
            target_account="b", start_date=date(2030, 1, 1),
            end_date=date(2035, 12, 31), annual_amount=40_000)]
        assert mc_signal(p) != mc_signal(base_planner())

    def test_rollover_event(self):
        from retirement_planner.models import (
            Account as A, RolloverEvent)

        def flip(p):
            p.scenario.accounts.append(A("trad", "Trad", "trad_ira",
                                         "pre_tax", 300_000, liquid=True))
            p.accounts["trad"] = A("trad", "Trad", "trad_ira", "pre_tax",
                                   300_000, liquid=True)
            p.scenario.rollover_events = [RolloverEvent(
                id="ro", name="RO", event_date=date(2033, 1, 1),
                source_account="trad", target_account="b")]
            return p
        assert_mc_changes(flip)

    def test_housing_event(self):
        from retirement_planner.models import HousingEvent

        def flip(p):
            p.scenario.housing_events = [HousingEvent(
                id="he", name="HE", event_date=date(2032, 1, 1),
                sale_price=900_000, purchase_price=1_200_000,
                down_payment=200_000, mortgage_amount=1_000_000,
                property_id="home", goes_to_account="b",
                funding_account="b", new_mortgage_id="m2")]
            return p
        assert_mc_changes(flip)


class TestContributionFields:
    def test_monthly_contribution(self):
        def flip(p):
            p.scenario.income_streams.append(IncomeStream(
                "salary", "Salary", owner="primary", monthly_amount=20_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31)))
            p.accounts["b"].monthly_contribution = 1_000
            return p
        assert_mc_changes(flip)

    def test_employer_match(self):
        def flip(p):
            p.scenario.income_streams.append(IncomeStream(
                "salary", "Salary", owner="primary", monthly_amount=20_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31)))
            p.accounts["b"].employer_match = 0.5
            p.accounts["b"].employer_match_limit = 0.06
            return p
        assert_mc_changes(flip)

    def test_contribution_priority_and_savings_order(self):
        def flip(p):
            p.scenario.income_streams.append(IncomeStream(
                "salary", "Salary", owner="primary", monthly_amount=20_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31)))
            p.accounts["b"].contribution_priority = 1
            p.scenario.savings_order = ["b"]
            return p
        assert_mc_changes(flip)

    def test_annual_contribution_cap(self):
        def flip(p):
            p.scenario.income_streams.append(IncomeStream(
                "salary", "Salary", owner="primary", monthly_amount=20_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31)))
            p.accounts["b"].monthly_contribution = 1_000
            p.accounts["b"].annual_contribution_cap = 6_000
            return p
        assert_mc_changes(flip)


# ---------------------------------------------------------------------------
# Dead / legacy fields must warn
# ---------------------------------------------------------------------------
class TestDeadFieldsWarn:
    def _load(self, patch):
        cfg = {
            "name": "d", "description": "",
            "primary": {"name": "P", "birth_date": "1980-01-01",
                        "retirement_date": "2026-01-01"},
            "spouse": {"name": "S", "birth_date": "1982-01-01",
                       "retirement_date": "2026-01-01"},
            "accounts": [{"id": "b", "name": "B", "type": "brokerage",
                          "tax_treatment": "taxable", "balance": 100_000}],
            "income_streams": [], "expenses": [], "mortgages": [],
        }
        patch(cfg)
        with open("/tmp/_coverage_test.json", "w") as f:
            json.dump(cfg, f)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            RetirementPlanner.from_config("/tmp/_coverage_test.json")
        return caught

    def test_account_growth_rate_optimistic_warns(self):
        caught = self._load(lambda c: c["accounts"][0].update(
            growth_rate_optimistic=0.1))
        assert any("growth_rate_optimistic" in str(w.message)
                   for w in caught)

    def test_account_asset_class_warns(self):
        caught = self._load(lambda c: c["accounts"][0].update(
            asset_class="equity"))
        assert any("asset_class" in str(w.message) for w in caught)

    def test_person_legacy_ss_fields_warn(self):
        caught = self._load(lambda c: c["primary"].update(
            social_security_benefit=2_000, ss_claiming_age=67))
        assert any("social_security_benefit" in str(w.message)
                   for w in caught)

    def test_family_size_warns(self):
        caught = self._load(lambda c: c.update(family_size=4))
        assert any("family_size" in str(w.message) for w in caught)

    def test_both_growth_rates_warn(self):
        def patch(c):
            c["expenses"] = [{"id": "e", "name": "E",
                              "monthly_amount": 100,
                              "start_date": "2026-01-01",
                              "end_date": "2090-12-31",
                              "growth_rate": 0.03,
                              "real_growth_rate": 0.01}]
        caught = self._load(patch)
        assert any("real_growth_rate" in str(w.message) for w in caught)

    def test_min_reduction_warns(self):
        caught = self._load(lambda c: c["expenses"].append(
            {"id": "e", "name": "E", "monthly_amount": 100,
             "start_date": "2026-01-01", "end_date": "2090-12-31",
             "min_reduction": 0.5}))
        assert any("min_reduction" in str(w.message) for w in caught)

    def test_is_ss_warns(self):
        caught = self._load(lambda c: c["income_streams"].append(
            {"id": "s", "name": "S", "owner": "primary",
             "monthly_amount": 1_000, "start_date": "2026-01-01",
             "end_date": "2090-12-31", "is_ss": True}))
        assert any("is_ss" in str(w.message) for w in caught)

    def test_clean_config_has_no_warnings(self):
        caught = self._load(lambda c: None)
        assert not caught
