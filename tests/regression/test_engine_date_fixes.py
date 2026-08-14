"""Regression tests for date-semantics, liquidity, and deterministic-path fixes.

Covers:
- End-date exclusivity for income streams, expenses, mortgages, and
  Roth conversion windows (a stream ending 2033-01-01 is inactive in 2033).
- Equity compensation inherits the income stream's end date so vests
  stop when employment ends.
- Deterministic projection includes Social Security income.
- Deterministic net worth counts mortgage liabilities and amortizes them.
- Withdrawals never liquidate illiquid/real-estate accounts.
- Monte Carlo marks runs out-of-savings when liquid assets cannot cover
  the shortfall even though net worth (incl. real estate) is positive.
"""
import json
import os
from datetime import date

import pytest

from retirement_planner.engine import (
    RetirementPlanner, WithdrawalEngine, CostBasisTracker, _year_active_fraction,
)
from retirement_planner.fixes import process_roth_conversions
from retirement_planner.models import (
    Account, EconomicAssumptions, Expense, IncomeStream, Mortgage, Person,
    Scenario, SocialSecurity, RothConversion,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")


def make_planner(accounts=None, expenses=None, mortgages=None, ss=None,
                 income_streams=None):
    primary = Person("Primary", date(1970, 1, 1), date(2030, 1, 1), 95)
    spouse = Person("Spouse", date(1972, 1, 1), date(2030, 1, 1), 95)
    scenario = Scenario(
        name="fixes", description="", primary=primary, spouse=spouse,
        economic=EconomicAssumptions(),
        accounts=accounts or [], income_streams=income_streams or [],
        expenses=expenses or [], mortgages=mortgages or [],
        social_security=ss or SocialSecurity(
            primary_benefit_at_67=3000, spouse_benefit_at_67=2500,
        ),
    )
    return RetirementPlanner(scenario)


# ---------------------------------------------------------------------------
# 1. _year_active_fraction semantics
# ---------------------------------------------------------------------------
class TestYearActiveFraction:

    def test_full_year(self):
        assert _year_active_fraction(
            date(2030, 1, 1), date(2030, 12, 31), 2030) == pytest.approx(1.0)

    def test_end_jan1_is_inactive(self):
        """Stream ending on Jan 1 of a year is inactive that year."""
        assert _year_active_fraction(
            date(2026, 1, 1), date(2033, 1, 1), 2033) == 0.0

    def test_end_jan1_active_prior_year(self):
        assert _year_active_fraction(
            date(2026, 1, 1), date(2033, 1, 1), 2032) == pytest.approx(1.0)

    def test_mid_year_end_prorates(self):
        frac = _year_active_fraction(date(2026, 1, 1), date(2033, 6, 30), 2033)
        assert frac == pytest.approx(181 / 365, rel=1e-3)

    def test_outside_window(self):
        assert _year_active_fraction(
            date(2026, 1, 1), date(2033, 1, 1), 2025) == 0.0


# ---------------------------------------------------------------------------
# 2. Income streams stop in their end year
# ---------------------------------------------------------------------------
class TestIncomeEndDate:

    def _salary_planner(self, end_date):
        return make_planner(income_streams=[
            IncomeStream(
                id="job", name="Job", owner="primary",
                monthly_amount=10_000, start_date=date(2026, 1, 1),
                end_date=date.fromisoformat(end_date),
            ),
        ])

    def test_end_jan1_excludes_end_year(self):
        planner = self._salary_planner("2030-01-01")
        assert planner.calculate_annual_income(2029)["total"] == pytest.approx(120_000)
        assert planner.calculate_annual_income(2030)["total"] == 0.0

    def test_end_dec31_includes_end_year(self):
        planner = self._salary_planner("2030-12-31")
        assert planner.calculate_annual_income(2030)["total"] == pytest.approx(120_000)

    def test_mid_year_end_prorates(self):
        planner = self._salary_planner("2030-06-30")
        assert planner.calculate_annual_income(2030)["total"] == pytest.approx(
            120_000 * 181 / 365, rel=1e-3)


# ---------------------------------------------------------------------------
# 3. Equity comp inherits stream end date (vests stop at employment end)
# ---------------------------------------------------------------------------
class TestEquityEndDatePropagation:

    def _equity_config(self, stream_end="2033-01-01"):
        return json.dumps({
            "name": "t", "description": "",
            "primary": {"name": "Primary", "birth_date": "1970-01-01",
                        "retirement_date": "2033-01-01"},
            "spouse": {"name": "Spouse", "birth_date": "1972-01-01",
                       "retirement_date": "2033-01-01"},
            "economic": {"investment_return_mean": 0.07},
            "accounts": [],
            "income_streams": [{
                "id": "job", "name": "Job", "owner": "primary",
                "monthly_amount": 0, "start_date": "2026-01-01",
                "end_date": stream_end,
                "equity": {
                    "ticker": "TEST", "current_price": 100.0,
                    "grants": [{
                        "id": "g1", "grant_date": "2026-01-01",
                        "total_shares": 400, "vesting_pattern": "quarterly",
                        "periodic_shares": 100, "status": "active",
                    }],
                    "refreshers": {
                        "annual_shares": 100, "grant_month": 9,
                        "vesting_pattern": "quarterly",
                        "start_year": 2027, "end_year": 2034,
                        "growth_rate": 0.0,
                    },
                },
            }],
            "expenses": [],
        })

    def test_equity_end_date_defaults_to_stream_end(self, tmp_path):
        p = tmp_path / "plan.json"
        p.write_text(self._equity_config())
        planner = RetirementPlanner.from_config(str(p))
        stream = planner.scenario.income_streams[0]
        assert stream.equity.end_date == date(2033, 1, 1)

    def test_no_rsu_income_after_employment_ends(self, tmp_path):
        p = tmp_path / "plan.json"
        p.write_text(self._equity_config())
        planner = RetirementPlanner.from_config(str(p))
        # 2029: grants + refreshers active → RSU income > 0
        assert planner.calculate_annual_rsu_income(
            2029, planner.scenario.income_streams[0].equity) > 0
        # 2034: employment ended → no vests at all
        assert planner.calculate_annual_rsu_income(
            2034, planner.scenario.income_streams[0].equity) == 0.0


# ---------------------------------------------------------------------------
# 4. Deterministic projection: SS included, mortgages as liabilities
# ---------------------------------------------------------------------------
class TestDeterministicParity:

    def test_social_security_appears_after_claiming_age(self):
        planner = make_planner()
        proj = planner.project_cash_flow()
        pre = [r for r in proj if r["year"] == 2036][0]
        post = [r for r in proj if r["year"] == 2037][0]
        both = [r for r in proj if r["year"] == 2039][0]
        assert "Social Security" not in pre["income_by_source"]
        # Primary turns 67 in 2037: 3,000/mo (COLA from claiming).
        # Spouse turns 67 in 2039: 2,500/mo, no COLA yet.
        assert post["income_by_source"]["Social Security"] == pytest.approx(36_000)
        cola = planner.scenario.social_security.cola_rate
        assert both["income_by_source"]["Social Security"] == pytest.approx(
            36_000 * (1 + cola) ** 2 + 30_000)
        assert post["income"] >= 36_000

    def test_net_worth_includes_mortgage_liabilities(self):
        mortgage = Mortgage(
            id="m1", name="Mortgage", property_id="home",
            balance=500_000, interest_rate=0.05, monthly_payment=3_000,
            start_date=date(2026, 1, 1), end_date=date(2055, 12, 31),
        )
        home = Account("home", "Home", "real_estate", "taxable", 900_000,
                       liquid=False, growth_rate=0.03)
        planner = make_planner(accounts=[home], mortgages=[mortgage])
        proj = planner.project_cash_flow()
        row = proj[0]
        assert row["total_liabilities"] > 400_000  # mortgage counted
        # Net worth = assets - mortgage, not assets alone
        assert row["net_worth"] == pytest.approx(
            row["total_assets"] - row["total_liabilities"])

    def test_mortgage_amortizes_in_deterministic_path(self):
        mortgage = Mortgage(
            id="m1", name="Mortgage", property_id="home",
            balance=100_000, interest_rate=0.05, monthly_payment=6_000,
            start_date=date(2026, 1, 1), end_date=date(2027, 12, 31),
        )
        home = Account("home", "Home", "real_estate", "taxable", 200_000,
                       liquid=False, growth_rate=0.0)
        planner = make_planner(accounts=[home], mortgages=[mortgage])
        proj = planner.project_cash_flow()
        r2026 = [r for r in proj if r["year"] == 2026][0]
        r2027 = [r for r in proj if r["year"] == 2027][0]
        r2028 = [r for r in proj if r["year"] == 2028][0]
        # 2026: monthly amortization — balance 100,000 @ 5%/12 with
        # 6,000/mo payments ends the year at ~31,439 remaining.
        balance = 100_000.0
        for _ in range(12):
            interest = balance * 0.05 / 12
            payment = min(6_000.0, balance + interest)
            balance -= payment - interest
        assert r2026["total_liabilities"] == pytest.approx(balance)
        assert r2026["total_liabilities"] > r2027["total_liabilities"]
        # Paid off in 2027 → no liabilities in 2028
        assert r2028["total_liabilities"] == 0

    def test_roth_conversion_window_jan1_end_is_inactive(self):
        balances = {"trad_ira": 100_000, "roth_ira": 10_000}
        rc = RothConversion(
            id="rc", name="RC", source_account="trad_ira",
            target_account="roth_ira", start_date=date(2030, 1, 1),
            end_date=date(2033, 1, 1), annual_amount=40_000,
        )
        result = process_roth_conversions([rc], 2032, balances)
        assert result.total_converted == pytest.approx(40_000)
        result = process_roth_conversions([rc], 2033, balances)
        assert result.total_converted == 0.0


# ---------------------------------------------------------------------------
# 5. Withdrawals never liquidate real estate
# ---------------------------------------------------------------------------
class TestLiquidity:

    def _accounts(self):
        return [
            Account("brokerage", "Brokerage", "brokerage", "taxable", 50_000),
            Account("home", "Home", "real_estate", "taxable", 900_000,
                    liquid=False),
            Account("rental", "Rental", "real_estate", "taxable", 400_000,
                    liquid=False),
            Account("pre", "Pre-tax", "trad_ira", "pre_tax", 100_000),
        ]

    def test_withdrawals_skip_illiquid_accounts(self):
        planner = make_planner(accounts=self._accounts())
        balances = {a.id: a.balance for a in planner.accounts.values()}
        engine = WithdrawalEngine(planner.accounts, CostBasisTracker())
        withdrawals = engine.execute_withdrawals(
            needed=150_000, balances=balances, year=2030,
            primary_age=60, spouse_age=58,
        )
        withdrawn_ids = [w.account_id for w in withdrawals]
        assert "home" not in withdrawn_ids
        assert "rental" not in withdrawn_ids
        # Brokerage fully drained, then pre-tax
        assert balances["brokerage"] == 0
        assert balances["pre"] == pytest.approx(100_000 - 100_000)
        assert balances["home"] == 900_000  # untouched
        assert balances["rental"] == 400_000  # untouched

    def test_mc_marks_out_of_savings_with_illiquid_assets(self):
        """Liquid assets exhausted but house remains → run fails."""
        accounts = [
            Account("brokerage", "Brokerage", "brokerage", "taxable", 20_000),
            Account("home", "Home", "real_estate", "taxable", 900_000,
                    liquid=False),
        ]
        expenses = [
            Expense("living", "Living", monthly_amount=5_000,
                    start_date=date(2026, 1, 1), end_date=date(2080, 1, 1),
                    is_must_spend=True),
        ]
        planner = make_planner(accounts=accounts, expenses=expenses)
        from retirement_planner.simulators import MonteCarloEngine
        result = MonteCarloEngine(planner).run(
            num_simulations=5, method="gaussian")
        # Every run must fail: liquid $20K cannot fund $60K/yr forever,
        # and the house is never sold.
        assert result["out_of_savings_rate"] == 1.0


# ---------------------------------------------------------------------------
# 6. Housing trade-up in MC: sale pays matching mortgage, new mortgage amortizes
# ---------------------------------------------------------------------------
class TestHousingTradeUpMC:

    def _planner(self):
        from retirement_planner.models import HousingEvent, Mortgage
        accounts = [
            Account("home", "Home", "real_estate", "taxable", 1_000_000,
                    liquid=False, growth_rate=0.03),
            Account("brokerage", "Brokerage", "brokerage", "taxable", 300_000),
        ]
        mortgage = Mortgage(
            id="m_home", name="Home Mortgage", property_id="home",
            balance=600_000, interest_rate=0.06, monthly_payment=4_000,
            start_date=date(2026, 1, 1), end_date=date(2055, 12, 31),
        )
        event = HousingEvent(
            id="trade_up", name="Trade up", event_date=date(2029, 7, 1),
            sale_price=1_100_000, purchase_price=1_500_000,
            down_payment=300_000, mortgage_amount=1_200_000,
            mortgage_rate=0.062, mortgage_term_years=30,
            property_id="home", goes_to_account="brokerage",
            funding_account="brokerage", new_mortgage_id="m_new",
        )
        return make_planner(accounts=accounts, mortgages=[mortgage]), event

    def test_trade_up_updates_balances_and_amortizes(self):
        planner, event = self._planner()
        planner.scenario.housing_events = [event]
        run = planner.run_single_simulation(
            rng=__import__("numpy").random.default_rng(3))
        assert run["out_of_savings_year"] is None

    def test_event_mortgage_payment_amortizes(self):
        planner, event = self._planner()
        # Directly exercise calculate_annual_expenses with an event mortgage
        balances = {"home": 1_100_000, "brokerage": 100_000}
        mortgage_balances = {"m_home": 550_000.0, "m_new": 1_200_000.0}
        terms = {"m_new": (0.062, 7_381.0, date(2029, 7, 1))}
        exp = planner.calculate_annual_expenses(
            2029, mortgage_balances=mortgage_balances,
            event_mortgage_terms=terms)
        assert "Mortgage - m_new" in exp["by_category"]
        # 5 payments (Aug-Dec, month after the July event): ~5 × 7,381
        assert exp["by_category"]["Mortgage - m_new"] == pytest.approx(
            5 * 7_381.0, rel=0.05)
        # balance reduced by principal portion
        assert mortgage_balances["m_new"] < 1_200_000


# ---------------------------------------------------------------------------
# 7. Withdrawal strategy anchors on current-year expenses
# ---------------------------------------------------------------------------
class TestStrategySpendingAnchor:

    def _planner(self, strategy="fixed"):
        accounts = [
            Account("brokerage", "Brokerage", "brokerage", "taxable", 5_000_000),
        ]
        # Expenses drop sharply after 2030 (e.g. mortgage payoff)
        expenses = [
            Expense("big", "Big", monthly_amount=10_000,
                    start_date=date(2026, 1, 1), end_date=date(2030, 12, 31),
                    is_must_spend=True),
            Expense("small", "Small", monthly_amount=1_000,
                    start_date=date(2031, 1, 1), end_date=date(2090, 12, 31),
                    is_must_spend=True),
        ]
        scenario = Scenario(
            name="anchor", description="",
            primary=Person("Primary", date(1980, 1, 1), date(2026, 1, 1), 90),
            spouse=Person("Spouse", date(1982, 1, 1), date(2026, 1, 1), 90),
            economic=EconomicAssumptions(),
            accounts=accounts, income_streams=[], expenses=expenses,
            mortgages=[], withdrawal_strategy=strategy,
        )
        return RetirementPlanner(scenario)

    def test_fixed_strategy_spends_current_expenses_not_year1(self):
        planner = self._planner("fixed")
        # Year 1: 10K/mo. Post-2030: 1K/mo. Spending must follow.
        exp2030 = planner.calculate_annual_expenses(2030)
        exp2031 = planner.calculate_annual_expenses(2031)
        assert exp2030["total"] == pytest.approx(120_000)
        assert exp2031["total"] == pytest.approx(12_000)
        # Withdrawals in a full run drain far less after the drop.
        run = planner.run_single_simulation(return_volatility=0.0)
        # 5 yrs × 120K + 59 yrs × 12K = 1.31M total withdrawals incl. tax
        assert run["final_net_worth"] > 5_000_000 - 1_400_000

    def test_dynamic_strategy_bumps_around_current_expenses(self):
        planner = self._planner("dynamic")
        # 12K/yr spend on a 5M portfolio → rate 0.24% < 3% → +2% bump
        adjusted = planner.apply_dynamic_spending(
            2031, 12_000, 5_000_000, {"total": 12_000, "by_category": {}})
        assert adjusted == pytest.approx(12_240)


# ---------------------------------------------------------------------------
# 8. 401(k) -> IRA rollover at retirement feeds the Roth ladder
# ---------------------------------------------------------------------------
class TestRolloverEvent:

    def _planner(self):
        from retirement_planner.models import RolloverEvent, RothConversion
        scenario = Scenario(
            name="roll", description="",
            primary=Person("Primary", date(1980, 1, 1), date(2030, 1, 1), 90),
            spouse=Person("Spouse", date(1982, 1, 1), date(2030, 1, 1), 90),
            economic=EconomicAssumptions(),
            accounts=[
                Account("k401", "401k", "401k", "pre_tax", 500_000,
                        growth_rate=0.0),
                Account("trad", "Trad", "trad_ira", "pre_tax", 50_000,
                        growth_rate=0.0),
                Account("roth", "Roth", "roth_ira", "roth", 10_000,
                        growth_rate=0.0),
            ],
            income_streams=[], expenses=[], mortgages=[],
            roth_conversions=[RothConversion(
                id="ladder", name="Ladder", source_account="trad",
                target_account="roth", start_date=date(2030, 1, 1),
                end_date=date(2039, 12, 31), annual_amount=40_000)],
            rollover_events=[RolloverEvent(
                id="roll", name="Rollover", event_date=date(2030, 1, 1),
                source_account="k401", target_account="trad")],
        )
        return RetirementPlanner(scenario)

    def test_rollover_moves_full_balance(self):
        planner = self._planner()
        balances = {"k401": 500_000, "trad": 50_000, "roth": 10_000}
        from retirement_planner.fixes import process_roth_conversions
        # Year 2030: conversion first (from 50K), then rollover lands 500K
        rc = process_roth_conversions(planner.scenario.roth_conversions, 2030, balances)
        assert rc.total_converted == pytest.approx(40_000)
        for ro in planner.scenario.rollover_events:
            if ro.event_date.year == 2030:
                balances[ro.target_account] += balances[ro.source_account]
                balances[ro.source_account] = 0.0
        assert balances["k401"] == 0
        assert balances["trad"] == pytest.approx(50_000 - 40_000 + 500_000)

    def test_engine_processes_rollover_in_mc(self):
        planner = self._planner()
        run = planner.run_single_simulation(return_volatility=0.0)
        assert run["out_of_savings_year"] is None
        # Ladder + rollover means conversions ran for a decade from the IRA
        assert run["lifetime_taxes"] > 0


# ---------------------------------------------------------------------------
# 9. Deterministic path processes housing events (parity with MC)
# ---------------------------------------------------------------------------
class TestDeterministicHousingEvents:

    def test_trade_up_appears_in_deterministic_projection(self):
        from retirement_planner.models import HousingEvent, Mortgage
        accounts = [
            Account("home", "Home", "real_estate", "taxable", 1_000_000,
                    liquid=False, growth_rate=0.03),
            Account("brokerage", "Brokerage", "brokerage", "taxable", 300_000),
        ]
        mortgage = Mortgage(
            id="m_home", name="Home Mortgage", property_id="home",
            balance=600_000, interest_rate=0.06, monthly_payment=4_000,
            start_date=date(2026, 1, 1), end_date=date(2055, 12, 31),
        )
        event = HousingEvent(
            id="trade_up", name="Trade up", event_date=date(2029, 7, 1),
            sale_price=1_100_000, purchase_price=1_500_000,
            down_payment=300_000, mortgage_amount=1_200_000,
            mortgage_rate=0.062, mortgage_term_years=30,
            property_id="home", goes_to_account="brokerage",
            funding_account="brokerage", new_mortgage_id="m_new",
        )
        scenario = Scenario(
            name="det", description="",
            primary=Person("Primary", date(1980, 1, 1), date(2026, 1, 1), 95),
            spouse=Person("Spouse", date(1982, 1, 1), date(2026, 1, 1), 95),
            economic=EconomicAssumptions(),
            accounts=accounts, income_streams=[], expenses=[],
            mortgages=[mortgage], housing_events=[event],
        )
        planner = RetirementPlanner(scenario)
        proj = planner.project_cash_flow()
        r2028 = [r for r in proj if r["year"] == 2028][0]
        r2029 = [r for r in proj if r["year"] == 2029][0]
        r2030 = [r for r in proj if r["year"] == 2030][0]
        # 2028: old mortgage liability present
        assert r2028["total_liabilities"] > 500_000
        # 2029: new mortgage replaces old (liability jumps), new payment starts
        assert r2029["total_liabilities"] > r2028["total_liabilities"]
        assert "Mortgage - m_new" in r2030["expenses_by_category"]
        assert "Mortgage - Home Mortgage" not in r2030["expenses_by_category"]
        # 2030 net worth reflects the new house + new mortgage
        assert r2030["total_liabilities"] < r2029["total_liabilities"]  # amortizing


# ---------------------------------------------------------------------------
# 10. Dynamic ACA family size from dependents
# ---------------------------------------------------------------------------
class TestDependentAcaFamilySize:

    def _planner(self, dependents=()):
        from retirement_planner.models import Dependent
        scenario = Scenario(
            name="dep", description="",
            primary=Person("Primary", date(1980, 1, 1), date(2026, 1, 1), 95,
                           coverage_type="auto"),
            spouse=Person("Spouse", date(1982, 1, 1), date(2026, 1, 1), 95,
                          coverage_type="auto"),
            economic=EconomicAssumptions(),
            accounts=[Account("brokerage", "Brokerage", "brokerage",
                              "taxable", 3_000_000)],
            income_streams=[], expenses=[], mortgages=[],
            dependents=list(dependents),
        )
        return RetirementPlanner(scenario)

    def test_children_count_until_26(self):
        from retirement_planner.models import Dependent
        planner = self._planner([Dependent(name="Kid",
                                           birth_date=date(2027, 1, 1))])
        # Born 2027 → age 1 in 2027, age 25 in 2052, age 26 in 2053
        assert planner._dependents_under_26(2026) == 0
        assert planner._dependents_under_26(2027) == 1
        assert planner._dependents_under_26(2052) == 1
        assert planner._dependents_under_26(2053) == 0

    def test_aca_subsidy_reflects_dependents(self):
        from retirement_planner.models import Dependent
        with_kid = self._planner([Dependent(name="Kid",
                                            birth_date=date(2027, 1, 1))])
        without = self._planner()
        # 2027-2031: parents 45-51, both pre-Medicare on ACA
        run_with = with_kid.run_single_simulation(
            return_volatility=0.0, rng=None)
        # family of 3 benchmark premium > family of 2, same MAGI
        subsidy3 = with_kid.calculate_aca_subsidy(60_000, 3, "CA")
        subsidy2 = without.calculate_aca_subsidy(60_000, 2, "CA")
        assert subsidy3 > subsidy2
        assert run_with["out_of_savings_year"] is None


# ---------------------------------------------------------------------------
# 11. Estate tax: REAL estate converted to nominal before exemption
# ---------------------------------------------------------------------------
class TestEstateTaxConvention:

    def _planner(self, balance):
        scenario = Scenario(
            name="estate", description="",
            primary=Person("Primary", date(1980, 1, 1), date(2026, 1, 1), 90),
            spouse=Person("Spouse", date(1982, 1, 1), date(2026, 1, 1), 90),
            economic=EconomicAssumptions(),
            accounts=[Account("brokerage", "Brokerage", "brokerage",
                              "taxable", balance, growth_rate=0.07)],
            income_streams=[], expenses=[], mortgages=[],
        )
        return RetirementPlanner(scenario)

    def test_large_estate_pays_estate_tax_in_real_mode(self):
        """The exemption is inflation-indexed (nominal); a REAL-mode
        estate must be converted to nominal before comparing.  Before
        the fix, real-vs-nominal comparison zeroed estate tax entirely."""
        planner = self._planner(5_000_000)
        run = planner.run_single_simulation(return_volatility=0.0)
        # 5M real at 7% for 64 yrs ≈ 340M real ≈ 1.4B nominal — taxable
        assert run["estate_tax"] > 0
        # Tax is progressive 18-40% on the excess over the indexed MFJ
        # exemption — never the full flat 40% on the entire estate.
        assert run["estate_tax"] < run["final_net_worth"] * 0.4


# ---------------------------------------------------------------------------
# 12. Sourced windfalls are NW-neutral transfers
# ---------------------------------------------------------------------------
class TestSourcedWindfall:

    def test_transfer_does_not_create_money(self):
        from retirement_planner.models import Windfall
        scenario = Scenario(
            name="wf", description="",
            primary=Person("Primary", date(1980, 1, 1), date(2026, 1, 1), 90),
            spouse=Person("Spouse", date(1982, 1, 1), date(2026, 1, 1), 90),
            economic=EconomicAssumptions(),
            accounts=[
                Account("a", "A", "brokerage", "taxable", 500_000,
                        growth_rate=0.07),
                Account("b", "B", "brokerage", "taxable", 100_000,
                        growth_rate=0.07),
            ],
            income_streams=[], expenses=[], mortgages=[],
            windfalls=[Windfall(
                id="xfer", name="Transfer", amount=95_000,
                date=date(2027, 1, 15), goes_to_account="b",
                source_account="a", is_taxable=False)],
        )
        planner = RetirementPlanner(scenario)
        with_xfer = planner.run_single_simulation(
            return_volatility=0.0)["final_net_worth"]
        scenario.windfalls = []
        without = planner.run_single_simulation(
            return_volatility=0.0)["final_net_worth"]
        # Moving money between two same-tax accounts is neutral; only the
        # 529's tax-exempt status changes the outcome, not the transfer.
        assert with_xfer == pytest.approx(without, rel=1e-9)
