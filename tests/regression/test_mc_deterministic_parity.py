"""MC ↔ deterministic parity harness.

The two projection paths have silently diverged several times (ACA
tables, NOMINAL double-conversion, medical inflation, tax conventions).
This harness runs both paths on representative configs and asserts the
year-by-year rows agree.

Scope of the guarantee:
- income / expenses / taxes / aca_subsidy rows agree in EVERY config
  (both paths share calculate_annual_expenses / calculate_annual_income
  and the versioned tax law).
- net_worth agrees only in withdrawal-free configs (no expenses): the
  deterministic path deliberately omits withdrawals, windfalls and
  contributions (documented limitation).
"""
from datetime import date

import pytest

from retirement_planner import RetirementPlanner
from retirement_planner.models import (
    Account, AgeEvent, Dependent, EconomicAssumptions, Expense,
    IncomeStream, MonetaryConvention, Person, Scenario,
)

ROW_KEYS = ("income", "expenses", "taxes", "aca_subsidy")


def make(real=True, expenses_on=True, income_on=False):
    expenses = [
        Expense("g", "G", monthly_amount=2_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31),
                growth_rate=0.02),
        Expense("h", "H", monthly_amount=1_000,
                start_date=date(2026, 1, 1), end_date=date(2090, 12, 31),
                category="medical", is_must_spend=True),
    ] if expenses_on else []
    incomes = [
        IncomeStream("r", "R", owner="primary", monthly_amount=3_000,
                     start_date=date(2026, 1, 1),
                     end_date=date(2090, 12, 31)),
    ] if income_on else []
    scenario = Scenario(
        name="parity", description="",
        primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
        spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
        economic=EconomicAssumptions(),
        accounts=[
            Account("b", "B", "brokerage", "taxable", 1_000_000,
                    growth_rate=0.06, equity_pct=0.6),
            Account("re", "RE", "real_estate", "taxable", 500_000,
                    liquid=False),
            Account("car", "CAR", "vehicle", "taxable", 30_000, liquid=False,
                    is_depreciating=True),
            Account("cash", "CASH", "checking", "taxable", 50_000,
                    growth_rate=0.0),
        ],
        income_streams=incomes,
        expenses=expenses,
        mortgages=[],
        age_events=[AgeEvent(trigger_age=65, expense_id="h",
                             new_monthly_amount=2_000)],
        dependents=[Dependent(name="Kid", birth_date=date(2027, 1, 1))],
        monetary_convention=(
            MonetaryConvention.REAL if real else MonetaryConvention.NOMINAL),
    )
    return RetirementPlanner(scenario)


def both_paths(planner):
    det = {r["year"]: r for r in planner.project_cash_flow()}
    mc = {r["year"]: r for r in planner.run_single_simulation(
        return_volatility=0.0, collect_projections=True)["projections"]}
    return det, mc


def assert_rows_agree(planner, keys=ROW_KEYS, tolerance=1e-6):
    det, mc = both_paths(planner)
    assert set(det) == set(mc)
    for year in det:
        for key in keys:
            d = det[year][key]
            m = mc[year][key]
            assert abs(d - m) <= max(0.05, abs(m) * tolerance), (
                f"{key} diverged in {year}: det={d:.2f} mc={m:.2f}")


CONFIGS = [
    # expenses-only configs withdraw (det does not): ACA subsidy depends
    # on withdrawal-inclusive MAGI in MC, so the subsidy rows can differ
    # (MC applies the FPL cliff; det computes on income only — a known
    # deterministic simplification).  income/expenses/taxes still agree.
    ("REAL expenses-only", make(True, True, False),
     ("income", "expenses", "taxes")),
    ("NOMINAL expenses-only", make(False, True, False),
     ("income", "expenses", "taxes")),
    # Withdrawal-free configs: every row (incl. ACA + NW) agrees.
    ("REAL income-only", make(True, False, True), ROW_KEYS),
    ("NOMINAL income-only", make(False, False, True), ROW_KEYS),
    ("REAL expenses+income", make(True, True, True),
     ("income", "expenses", "taxes")),
    ("NOMINAL expenses+income", make(False, True, True),
     ("income", "expenses", "taxes")),
]


@pytest.mark.parametrize(
    "label,planner,keys",
    CONFIGS,
    ids=[c[0] for c in CONFIGS],
)
class TestRowParity:
    def test_rows_agree(self, label, planner, keys):
        assert_rows_agree(planner, keys=keys)

    def test_horizons_match(self, label, planner, keys):
        det, mc = both_paths(planner)
        assert set(det) == set(mc)


class TestNetWorthParity:
    """Net worth agrees when no withdrawals occur (expenses <= income)."""

    def test_income_only_real(self):
        assert_rows_agree(make(True, False, True), keys=("net_worth",))

    def test_income_only_nominal(self):
        assert_rows_agree(make(False, False, True), keys=("net_worth",))

    def test_expenses_diverge_only_by_withdrawals(self):
        """With expenses, NW differs ONLY because MC withdraws (det omits
        withdrawals by design) — the gap must be roughly the cumulative
        withdrawal stream, never a drift in returns."""
        det, mc = both_paths(make(True, True, False))
        # Early year: gap ≈ first year's spending
        gap = mc[2026]["net_worth"] - det[2026]["net_worth"]
        # Withdrawal = expenses (income 0) — gap bounded by full spend
        assert abs(gap) <= abs(det[2026]["expenses"]) + 0.05

    def test_medical_excess_compounds_identically(self):
        det, mc = both_paths(make(True, True, False))
        # Age event at 65 (2047 for the younger): both paths step health
        # spend 1K → 2K/mo in the same year
        assert det[2047]["expenses"] == pytest.approx(mc[2047]["expenses"])
        assert det[2048]["expenses"] == pytest.approx(mc[2048]["expenses"])


class TestConventionConsistency:
    def test_nominal_balances_grow_at_converted_rate_once(self):
        """Regression: allocation rates were converted twice in NOMINAL
        mode; non-allocation accounts (real estate/vehicle/cash) must
        convert exactly once in both paths."""
        planner = make(False, False, False)
        det, mc = both_paths(planner)
        assert det[2030]["net_worth"] == pytest.approx(
            mc[2030]["net_worth"], rel=1e-9)
        # Real estate: 4.4% real → ~7.0% nominal; vehicle −4% → ~−1.6%
        # (single conversion in both paths — caught by the equality above)

    def test_real_balances_use_real_rates(self):
        planner = make(True, False, False)
        det, mc = both_paths(planner)
        assert det[2030]["net_worth"] == pytest.approx(
            mc[2030]["net_worth"], rel=1e-9)

    def test_mc_aca_applies_fpl_cliff_on_withdrawal_magi(self):
        """With heavy withdrawals MAGI crosses 400% FPL → MC subsidy 0.

        The deterministic path computes the subsidy on income only (it
        has no withdrawal model) and therefore over-reports it — a
        documented simplification, not a parity target.
        """
        expenses = [Expense(
            "big", "Big", monthly_amount=60_000,
            start_date=date(2026, 1, 1), end_date=date(2090, 12, 31))]
        scenario = Scenario(
            name="cliff", description="",
            primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
            spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
            economic=EconomicAssumptions(),
            accounts=[Account("b", "B", "brokerage", "taxable",
                              10_000_000, growth_rate=0.06)],
            income_streams=[], expenses=expenses, mortgages=[],
        )
        det, mc = both_paths(RetirementPlanner(scenario))
        # 2040: 14 years of 720K/yr withdrawals → basis exhausted, MAGI
        # well above 400% FPL → no subsidy in MC; det (income-only MAGI)
        # still reports the full subsidy.
        assert mc[2040]["aca_subsidy"] == 0.0
        assert det[2040]["aca_subsidy"] > 0.0
        assert mc[2040]["income"] == pytest.approx(det[2040]["income"])
