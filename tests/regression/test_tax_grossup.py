"""Regression tests for the MC tax gross-up fixed-point loop (Part 5.1).

Covers:
- Money conservation: retirement withdrawals fund expenses AND taxes,
  exactly once (no double-withdrawal across fixed-point passes).
- ACA subsidy phases out with withdrawal-inclusive MAGI (past the cliff
  the subsidy is $0; tax-free withdrawals leave it untouched).
- Social Security taxation includes withdrawal income (provisional
  income), so RMD-era households with SS pay materially more tax than
  without SS.
- Roth + SS retirement pays ~zero tax (tax-free combo sanity check).

Notes on test construction:
- SocialSecurity benefits are MONTHLY at age 67 (engine multiplies by 12).
- People are born 1980+ so the sim ends (longevity) before RMD age 73,
  avoiding the RMD-surplus edge case; the SS test deliberately uses
  RMD-age people to exercise the RMD floor.
- Expenses run past sim end so the fixed withdrawal strategy's
  base_spending equals actual expenses (a known engine quirk keeps
  spending base_spending even after expense streams end).
"""
from datetime import date

import pytest

from retirement_planner.engine import RetirementPlanner
from retirement_planner.models import (
    Account, EconomicAssumptions, Expense, Person, Scenario, SocialSecurity,
)


def make_planner(accounts, expenses, ss_benefits=(0.0, 0.0),
                 coverage="none", birth_years=(1980, 1982),
                 retirement_year=2030, longevity=65):
    primary = Person(
        "Primary", date(birth_years[0], 1, 1),
        date(retirement_year, 1, 1), longevity,
        coverage_type=coverage)
    spouse = Person(
        "Spouse", date(birth_years[1], 1, 1),
        date(retirement_year, 1, 1), longevity,
        coverage_type=coverage)
    scenario = Scenario(
        name="grossup", description="", primary=primary, spouse=spouse,
        economic=EconomicAssumptions(),
        accounts=accounts, income_streams=[], expenses=expenses,
        mortgages=[],
        social_security=SocialSecurity(
            primary_benefit_at_67=ss_benefits[0],
            spouse_benefit_at_67=ss_benefits[1],
            primary_claiming_age=67, spouse_claiming_age=67,
        ),
    )
    return RetirementPlanner(scenario)


def expense(monthly, start_year=2026, end_year=2099):
    return Expense(
        "living", "Living", monthly_amount=monthly,
        start_date=date(start_year, 1, 1),
        end_date=date(end_year, 12, 31),
        is_must_spend=True,
    )


# ---------------------------------------------------------------------------
# 1. Money conservation: final balance = initial - expenses - taxes
# ---------------------------------------------------------------------------
class TestMoneyConservation:

    def test_withdrawals_fund_expenses_plus_taxes_exactly_once(self):
        """The fixed-point loop must not double-withdraw across passes."""
        initial = 4_000_000
        annual_expenses = 120_000
        # Sim runs 2026..2047 (spouse born 1982, longevity 65) = 22 years
        num_years = 22
        planner = make_planner(
            accounts=[Account("trad", "Trad", "trad_ira", "pre_tax",
                              initial, growth_rate=0.0)],
            expenses=[expense(10_000)],
        )
        run = planner.run_single_simulation(
            return_volatility=0.0, collect_projections=True)

        assert run["out_of_savings_year"] is None
        assert run["lifetime_taxes"] > 0  # pre-tax withdrawals are ordinary
        # Balance falls by exactly (expenses + taxes), once per year.  The
        # survivor expense ratio (R6) scales post-first-death years to 75%,
        # so sum the actual per-year expenses from the projections rather
        # than the flat annual amount.
        total_expenses = sum(r["expenses"] for r in run["projections"])
        assert run["final_net_worth"] == pytest.approx(
            initial - total_expenses - run["lifetime_taxes"],
            abs=10.0)

    def test_no_withdrawals_when_income_covers_expenses(self):
        """A fully-funded retirement withdraws nothing and pays no tax
        (no phantom withdrawals from the fixed-point iterations)."""
        initial = 500_000
        annual_expenses = 12_000
        num_years = 22  # sim runs 2026..2047 (spouse longevity 65)
        planner = make_planner(
            accounts=[Account("roth", "Roth", "roth_ira", "roth",
                              initial, growth_rate=0.0)],
            expenses=[expense(1_000)],
        )
        run = planner.run_single_simulation(
            return_volatility=0.0, collect_projections=True)
        assert run["out_of_savings_year"] is None
        assert run["lifetime_taxes"] == 0.0
        # Sum actual per-year expenses (survivor ratio scales post-death
        # years) rather than the flat annual amount.
        total_expenses = sum(r["expenses"] for r in run["projections"])
        assert run["final_net_worth"] == pytest.approx(
            initial - total_expenses, rel=1e-9)


# ---------------------------------------------------------------------------
# 2. ACA subsidy responds to withdrawal-inclusive MAGI
# ---------------------------------------------------------------------------
class TestAcaMagi:

    def _couple(self, account):
        # Born 1966/1968: ACA years 2026-2030 (primary turns 65 in 2031).
        # $240K/yr spend → withdrawals far past the 400%-FPL cliff.
        return make_planner(
            accounts=[account],
            expenses=[expense(20_000)],
            coverage="auto", birth_years=(1966, 1968),
            retirement_year=2026, longevity=90,
        )

    def test_high_withdrawals_push_magi_past_cliff(self):
        """Pre-tax withdrawals ~$280K/yr → MAGI >> 400% FPL → no subsidy."""
        planner = self._couple(
            Account("trad", "Trad", "trad_ira", "pre_tax",
                    3_000_000, growth_rate=0.0))
        run = planner.run_single_simulation(return_volatility=0.0)
        assert run["aca_subsidy"] == pytest.approx(0.0, abs=1.0)

    def test_tax_free_withdrawals_keep_magi_low(self):
        """Roth withdrawals add nothing to MAGI → full subsidy."""
        planner = self._couple(
            Account("roth", "Roth", "roth_ira", "roth",
                    3_000_000, growth_rate=0.0))
        run = planner.run_single_simulation(return_volatility=0.0)
        # 5 ACA years of roughly the full benchmark premium.
        assert run["aca_subsidy"] > 50_000


# ---------------------------------------------------------------------------
# 3. Social Security taxation includes withdrawal income
# ---------------------------------------------------------------------------
class TestTaxableSsIncludesWithdrawals:

    def test_rmd_era_household_with_ss_pays_more_tax(self):
        """RMDs are floored regardless of SS, and SS becomes up to 85%
        taxable once provisional income (RMDs + half-SS) crosses $44K —
        so the same household pays materially more tax with SS."""
        def build(ss):
            # Born 1952/1954 → 74/72 in 2026: SS claimed, RMDs active.
            return make_planner(
                accounts=[Account("trad", "Trad", "trad_ira", "pre_tax",
                                  2_000_000, growth_rate=0.0)],
                expenses=[expense(10_000)],
                ss_benefits=ss,
                birth_years=(1952, 1954),
                retirement_year=2026, longevity=95,
            )
        with_ss = build((5_000, 4_000))   # $108K/yr combined
        without_ss = build((0.0, 0.0))
        taxes_with = with_ss.run_single_simulation(
            return_volatility=0.0)["lifetime_taxes"]
        taxes_without = without_ss.run_single_simulation(
            return_volatility=0.0)["lifetime_taxes"]
        assert taxes_with > taxes_without * 1.15

    def test_roth_plus_ss_is_tax_free(self):
        """Roth withdrawals + SS below the provisional-income threshold:
        nothing taxable, so the loop must not invent income."""
        planner = make_planner(
            accounts=[Account("roth", "Roth", "roth_ira", "roth",
                              2_000_000, growth_rate=0.0)],
            expenses=[expense(10_000)],
            ss_benefits=(5_000, 0.0),   # $60K/yr — half is $30K < $32K
            birth_years=(1952, 1954),
            retirement_year=2026, longevity=95,
        )
        run = planner.run_single_simulation(
            return_volatility=0.0, collect_projections=True)
        assert run["out_of_savings_year"] is None
        # Roth withdrawals are tax-free and SS ($60K/yr, half = $30K) sits
        # below the MFJ $32K provisional-income threshold, so no tax is due
        # WHILE both spouses are alive. After the first death the survivor
        # files Single, whose lower $25K threshold makes the same SS
        # partially taxable — correct per tax law (covered by the survivor
        # suite). Assert tax-free only in both-alive years.
        for row in run["projections"]:
            if row["primary_alive"] and row["spouse_alive"]:
                assert row["taxes"] == 0.0
