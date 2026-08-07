"""Tests for tech_comp.py — ESPP, NQSO, Mega-Backdoor Roth."""
import pytest
from datetime import date
from retirement_planner.tech_comp import (
    ESPPGrant, ESPPDisposition, calculate_espp_purchase_price,
    calculate_espp_income, simulate_espp_period,
    NQSOGrant, NQSOExercise, exercise_nqso, calculate_nqso_spread_tax,
    MegaBackdoorRoth, AfterTaxAccount,
)


class TestESPP:

    def test_lookback_lower_price(self):
        price = calculate_espp_purchase_price(100, 80, discount_pct=0.15, lookback=True)
        assert price == pytest.approx(80 * 0.85)

    def test_lookback_higher_start(self):
        price = calculate_espp_purchase_price(80, 100, discount_pct=0.15, lookback=True)
        assert price == pytest.approx(80 * 0.85)

    def test_no_lookback(self):
        price = calculate_espp_purchase_price(100, 80, discount_pct=0.15, lookback=False)
        assert price == pytest.approx(80 * 0.85)

    def test_qualifying_disposition(self):
        result = calculate_espp_income(100, 85, 120, is_qualifying=True)
        assert result["ordinary_income"] == 0
        assert result["capital_gain"] == pytest.approx(3500)

    def test_disqualifying_disposition(self):
        result = calculate_espp_income(100, 85, 120, is_qualifying=False)
        assert result["ordinary_income"] == pytest.approx(3500)
        assert result["capital_gain"] == 0

    def test_simulate_period(self):
        grant = ESPPGrant(
            id="espp1", ticker="NVDA",
            offering_start=date(2026, 1, 1),
            offering_end=date(2026, 6, 30),
            purchase_date=date(2026, 6, 30),
            discount_pct=0.15, lookback=True,
        )
        result = simulate_espp_period(grant, [100, 120], salary=200_000)
        assert result["shares"] > 0
        assert result["cost"] > 0
        assert result["immediate_gain"] > 0


class TestNQSO:

    def test_exercise_spread(self):
        grant = NQSOGrant(
            id="nqso1", ticker="NVDA",
            grant_date=date(2024, 1, 1),
            total_shares=1000,
            strike_price=50.0,
        )
        exercise = exercise_nqso(grant, 100, market_price=175.0)
        assert exercise.spread == pytest.approx(125.0)
        assert exercise.shares_exercised == 100
        assert exercise.total_tax > 0

    def test_cashless_exercise(self):
        grant = NQSOGrant(
            id="nqso1", ticker="NVDA",
            grant_date=date(2024, 1, 1),
            total_shares=1000,
            strike_price=50.0,
        )
        exercise = exercise_nqso(grant, 100, market_price=175.0, cashless=True)
        assert exercise.net_proceeds > 0
        assert exercise.net_proceeds < 12_500

    def test_spread_tax_estimate(self):
        tax = calculate_nqso_spread_tax(100, 50, 175)
        assert tax > 0
        assert tax == pytest.approx(12_500 * 0.5465)

    def test_out_of_money(self):
        grant = NQSOGrant(
            id="nqso1", ticker="NVDA",
            grant_date=date(2024, 1, 1),
            total_shares=1000,
            strike_price=200.0,
        )
        exercise = exercise_nqso(grant, 100, market_price=175.0)
        assert exercise.spread == 0
        assert exercise.total_tax == 0


class TestMegaBackdoorRoth:

    def test_after_tax_capacity(self):
        mbr = MegaBackdoorRoth(
            after_tax_401k_limit=70_000,
            elective_deferral_limit=23_500,
            employer_match_estimate=10_000,
        )
        # Capacity = 70K - 23.5K - 10K = 36.5K
        assert mbr.after_tax_capacity == pytest.approx(36_500)

    def test_calculate_annual(self):
        mbr = MegaBackdoorRoth()
        result = mbr.calculate_annual_after_tax(salary=200_000, after_tax_pct=0.10)
        # 10% of $200K = $20K, but capacity is ~$36.5K → $20K
        assert result == pytest.approx(20_000)

    def test_simulate_pipeline(self):
        mbr = MegaBackdoorRoth()
        result = mbr.simulate_pipeline(
            after_tax_contribution=20_000,
            years=10,
            growth_rate=0.07,
        )
        assert result["roth_balance"] > 200_000
        assert result["total_contributed"] == pytest.approx(200_000)
        assert result["tax_free_withdrawal"] == result["roth_balance"]


class TestAfterTaxAccount:

    def test_contribute_and_grow(self):
        acct = AfterTaxAccount()
        acct.contribute(10_000)
        assert acct.balance == 10_000
        assert acct.basis == 10_000
        acct.grow(0.10)
        assert acct.balance == 11_000
        assert acct.earnings == 1_000

    def test_convert_to_roth(self):
        acct = AfterTaxAccount()
        acct.contribute(10_000)
        acct.grow(0.10)
        converted = acct.convert_to_roth(5_000)
        assert converted == 5_000
        assert acct.balance == 6_000
