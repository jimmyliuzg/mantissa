"""Tests for Phase 0 fixes and Phase 1 tax lot tracking."""
import pytest
from datetime import date
from retirement_planner.fixes import (
    HousingEventResult, process_housing_event,
    RothConversionResult, process_roth_conversions,
    apply_medical_inflation, process_medical_expenses,
)
from retirement_planner.tax_lots import (
    TaxLot, TaxLotTracker, LiquidationResult,
    calculate_121_exclusion,
)


# ---------------------------------------------------------------------------
# Phase 0.1: Housing events
# ---------------------------------------------------------------------------
class TestHousingEvents:

    def test_sale_pays_off_mortgage(self):
        event = type('Event', (), {
            'event_id': 'e1', 'event_date': date(2030, 6, 1),
            'sale_price': 800_000, 'purchase_price': 0,
            'goes_to_account': 'brokerage',
        })()
        balances = {"brokerage": 100_000}
        mortgage = {"mortgage1": 200_000}

        result = process_housing_event(
            event, 2030, balances, mortgage,
            cost_basis=500_000, filing_status="MFJ",
        )
        assert result.event_type == "sale"
        assert result.mortgage_delta < 0  # mortgage paid off
        assert result.gain_realized == 300_000  # 800K - 500K basis

    def test_sale_121_exclusion(self):
        event = type('Event', (), {
            'event_id': 'e1', 'event_date': date(2030, 6, 1),
            'sale_price': 900_000, 'purchase_price': 0,
            'goes_to_account': 'brokerage',
        })()
        # Sold for $900K, basis $500K → $400K gain
        # §121 excludes $400K (under $500K MFJ limit)
        result = process_housing_event(
            event, 2030, {}, {},
            cost_basis=500_000, filing_status="MFJ",
        )
        assert result.tax_due == 0  # fully excluded

    def test_sale_over_121_limit(self):
        event = type('Event', (), {
            'event_id': 'e1', 'event_date': date(2030, 6, 1),
            'sale_price': 1_200_000, 'purchase_price': 0,
            'goes_to_account': 'brokerage',
        })()
        # Sold for $1.2M, basis $500K → $700K gain
        # §121 excludes $500K, taxable $200K
        result = process_housing_event(
            event, 2030, {}, {},
            cost_basis=500_000, filing_status="MFJ",
        )
        assert result.gain_realized == 700_000
        assert result.tax_due > 0  # tax on $200K gain

    def test_purchase_creates_mortgage(self):
        event = type('Event', (), {
            'event_id': 'e2', 'event_date': date(2028, 1, 1),
            'sale_price': 0, 'purchase_price': 800_000,
            'down_payment': 200_000, 'mortgage_amount': 600_000,
            'funding_account': 'brokerage',
        })()
        balances = {"brokerage": 300_000}
        mortgage = {}

        result = process_housing_event(
            event, 2028, balances, mortgage,
            cost_basis=0,
        )
        assert result.event_type == "purchase"
        assert result.account_delta == -200_000  # down payment
        assert result.mortgage_delta == 600_000  # new mortgage
        assert result.property_account_change == 800_000  # new property

    def test_wrong_year_noop(self):
        event = type('Event', (), {
            'event_id': 'e1', 'event_date': date(2030, 6, 1),
            'sale_price': 800_000, 'purchase_price': 0,
        })()
        result = process_housing_event(event, 2029, {}, {}, 500_000)
        assert result.event_type == "none"


# ---------------------------------------------------------------------------
# Phase 0.2: Roth conversions
# ---------------------------------------------------------------------------
class TestRothConversions:

    def _make_conversion(self, source, target, amount, start_year=2026, end_year=2030):
        return type('RC', (), {
            'source_account': source,
            'target_account': target,
            'annual_amount': amount,
            'start_date': date(start_year, 1, 1),
            'end_date': date(end_year, 12, 31),
        })()

    def test_conversion_moves_money(self):
        rc = self._make_conversion("401k", "roth_ira", 50_000)
        balances = {"401k": 500_000, "roth_ira": 100_000}

        result = process_roth_conversions([rc], 2026, balances)
        assert result.total_converted == 50_000
        assert balances["401k"] == 450_000
        assert balances["roth_ira"] == 150_000

    def test_conversion_adds_ordinary_income(self):
        rc = self._make_conversion("401k", "roth_ira", 50_000)
        result = process_roth_conversions([rc], 2026, {"401k": 500_000})
        assert result.ordinary_income_added == 50_000

    def test_insufficient_balance(self):
        rc = self._make_conversion("401k", "roth_ira", 50_000)
        balances = {"401k": 10_000}  # not enough
        result = process_roth_conversions([rc], 2026, balances)
        assert result.total_converted == 10_000  # takes what's available

    def test_inactive_conversion(self):
        rc = self._make_conversion("401k", "roth_ira", 50_000, start_year=2028)
        balances = {"401k": 500_000}
        result = process_roth_conversions([rc], 2026, balances)
        assert result.total_converted == 0

    def test_max_conversion_cap(self):
        rc = self._make_conversion("401k", "roth_ira", 50_000)
        balances = {"401k": 500_000}
        result = process_roth_conversions([rc], 2026, balances, max_conversion=30_000)
        assert result.total_converted == 30_000


# ---------------------------------------------------------------------------
# Phase 0.3: Medical inflation
# ---------------------------------------------------------------------------
class TestMedicalInflation:

    def test_no_inflation_at_start(self):
        result = apply_medical_inflation(10_000, 2026, 2026)
        assert result == 10_000

    def test_inflation_compounds(self):
        result = apply_medical_inflation(10_000, 2028, 2026,
                                          general_inflation=0.025,
                                          medical_inflation=0.034)
        # 2 years, excess = 0.9% per year
        expected = 10_000 * (1.009 ** 2)
        assert result == pytest.approx(expected)

    def test_process_medical_expenses(self):
        med_exp = type('Exp', (), {
            'category': 'healthcare',
            'monthly_amount': 500,
        })()
        result = process_medical_expenses([med_exp], 2028, 2026,
                                           general_inflation=0.025,
                                           medical_inflation=0.034)
        assert result > 0  # additional cost from medical inflation


# ---------------------------------------------------------------------------
# Phase 1: Tax lot tracking
# ---------------------------------------------------------------------------
class TestTaxLot:

    def test_lot_creation(self):
        lot = TaxLot(
            account_id="brokerage",
            purchase_date=date(2024, 1, 1),
            shares=100,
            cost_basis_per_share=50.0,
        )
        assert lot.total_cost == 5000
        assert lot.lot_id  # auto-generated

    def test_long_term_holding(self):
        lot = TaxLot(
            purchase_date=date(2024, 1, 1),
            shares=100,
            cost_basis_per_share=50.0,
        )
        assert lot.is_long_term(date(2025, 6, 1))    # > 1 year
        assert not lot.is_long_term(date(2024, 6, 1))  # < 1 year

    def test_split_lot(self):
        lot = TaxLot(
            purchase_date=date(2024, 1, 1),
            shares=100,
            cost_basis_per_share=50.0,
        )
        sold, remaining = lot.split(60)
        assert sold.shares == 60
        assert remaining.shares == 40


class TestTaxLotTracker:

    def test_add_and_query(self):
        tracker = TaxLotTracker()
        tracker.add_purchase("401k", 100, 50.0, date(2024, 1, 1))
        assert tracker.total_shares("401k") == 100
        assert tracker.total_basis("401k") == 5000

    def test_fifo_liquidation(self):
        tracker = TaxLotTracker()
        tracker.add_purchase("brokerage", 50, 100.0, date(2024, 1, 1))  # lot A
        tracker.add_purchase("brokerage", 50, 200.0, date(2024, 6, 1))  # lot B

        result = tracker.liquidate_with_price("brokerage", 60, 250.0,
                                               algorithm="fifo", sale_date=date(2025, 1, 2))
        assert result.total_shares == 60
        # FIFO: sells lot A first (50 shares @ $100) + 10 from lot B
        assert result.total_cost_basis == 50 * 100 + 10 * 200

    def test_hifo_liquidation(self):
        tracker = TaxLotTracker()
        tracker.add_purchase("brokerage", 50, 100.0, date(2024, 1, 1))  # low basis
        tracker.add_purchase("brokerage", 50, 200.0, date(2024, 6, 1))  # high basis

        result = tracker.liquidate_with_price("brokerage", 60, 250.0,
                                               algorithm="hifo", sale_date=date(2025, 1, 2))
        # HIFO: sells high basis first (50 shares @ $200) + 10 from low basis
        assert result.total_cost_basis == 50 * 200 + 10 * 100

    def test_hifo_minimizes_gains(self):
        tracker_fifo = TaxLotTracker()
        tracker_fifo.add_purchase("b", 50, 100.0, date(2024, 1, 1))
        tracker_fifo.add_purchase("b", 50, 200.0, date(2024, 6, 1))

        tracker_hifo = TaxLotTracker()
        tracker_hifo.add_purchase("b", 50, 100.0, date(2024, 1, 1))
        tracker_hifo.add_purchase("b", 50, 200.0, date(2024, 6, 1))

        r_fifo = tracker_fifo.liquidate_with_price("b", 60, 250.0, "fifo", date(2025, 1, 2))
        r_hifo = tracker_hifo.liquidate_with_price("b", 60, 250.0, "hifo", date(2025, 1, 2))

        assert r_hifo.total_gain <= r_fifo.total_gain  # HIFO minimizes gains

    def test_specific_id(self):
        tracker = TaxLotTracker()
        tracker.add_purchase("brokerage", 50, 100.0, date(2024, 1, 1))
        tracker.add_purchase("brokerage", 50, 200.0, date(2024, 6, 1))

        lots = tracker.get_lots("brokerage")
        lot_to_sell = lots[1].lot_id  # sell the second lot

        result = tracker.sell_specific("brokerage", {lot_to_sell: 50}, 250.0)
        assert result.total_shares == 50
        assert result.total_cost_basis == 50 * 200

    def test_specific_id_partial(self):
        tracker = TaxLotTracker()
        tracker.add_purchase("brokerage", 100, 150.0, date(2024, 1, 1))

        lots = tracker.get_lots("brokerage")
        lot_id = lots[0].lot_id

        # Sell only 30 of 100 shares
        result = tracker.sell_specific("brokerage", {lot_id: 30}, 200.0)
        assert result.total_shares == 30
        assert result.total_cost_basis == 30 * 150

        # 70 shares remain
        remaining = tracker.get_lots("brokerage")
        assert len(remaining) == 1
        assert remaining[0].shares == pytest.approx(70)

    def test_gain_split_short_long(self):
        tracker = TaxLotTracker()
        # Short-term lot (< 1 year)
        tracker.add_purchase("b", 50, 100.0, date(2024, 6, 1))
        # Long-term lot (> 1 year)
        tracker.add_purchase("b", 50, 100.0, date(2023, 1, 1))

        result = tracker.liquidate_with_price("b", 100, 200.0, "fifo", sale_date=date(2025, 1, 2))
        # FIFO: sells short-term first, then long-term
        assert result.short_term_gain > 0
        assert result.long_term_gain > 0


# ---------------------------------------------------------------------------
# §121 exclusion
# ---------------------------------------------------------------------------
class Test121Exclusion:

    def test_full_exclusion(self):
        excluded, taxable = calculate_121_exclusion(
            sale_price=900_000, cost_basis=500_000,
            filing_status="MFJ", years_owned=5, years_lived=5,
        )
        assert excluded == 400_000
        assert taxable == 0

    def test_partial_exclusion(self):
        excluded, taxable = calculate_121_exclusion(
            sale_price=1_200_000, cost_basis=500_000,
            filing_status="MFJ", years_owned=5, years_lived=5,
        )
        assert excluded == 500_000
        assert taxable == 200_000

    def test_single_filer(self):
        excluded, taxable = calculate_121_exclusion(
            sale_price=600_000, cost_basis=300_000,
            filing_status="SINGLE", years_owned=5, years_lived=5,
        )
        assert excluded == 250_000
        assert taxable == 50_000

    def test_not_enough_ownership(self):
        excluded, taxable = calculate_121_exclusion(
            sale_price=800_000, cost_basis=500_000,
            filing_status="MFJ", years_owned=1, years_lived=1,
        )
        assert excluded == 0
        assert taxable == 300_000
