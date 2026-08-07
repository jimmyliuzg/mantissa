"""Tests for monthly_events.py — ACA, IRMAA, RMD timing."""
import pytest
from retirement_planner.monthly_events import (
    MonthlyEvent, calculate_monthly_aca_subsidy, calculate_irmaa_assessment,
    calculate_rmd_events, process_year_events,
)


class TestMonthlyACASubsidy:

    def test_no_subsidy(self):
        events = calculate_monthly_aca_subsidy(0)
        assert events == []

    def test_full_year_subsidy(self):
        events = calculate_monthly_aca_subsidy(12_000, months_eligible=12)
        assert len(events) == 12
        assert all(e.name == "aca_subsidy" for e in events)
        assert all(e.amount == pytest.approx(-1_000) for e in events)

    def test_partial_year(self):
        events = calculate_monthly_aca_subsidy(6_000, months_eligible=6)
        assert len(events) == 6
        assert all(e.amount == pytest.approx(-1_000) for e in events)

    def test_months_sorted(self):
        events = calculate_monthly_aca_subsidy(12_000, 12)
        months = [e.month for e in events]
        assert months == list(range(1, 13))


class TestIRMAAAssessment:

    def test_under_65(self):
        events = calculate_irmaa_assessment(300_000, 5_000, current_age=64)
        assert events == []

    def test_no_surcharge(self):
        events = calculate_irmaa_assessment(200_000, 0, current_age=67)
        assert events == []

    def test_monthly_surcharge(self):
        events = calculate_irmaa_assessment(300_000, 4_800, current_age=70)
        assert len(events) == 12
        assert all(e.name == "irmaa_surcharge" for e in events)
        assert all(e.amount == pytest.approx(400) for e in events)
        assert events[0].metadata["magi_lookback"] == 300_000


class TestRMDEvents:

    def test_under_73(self):
        events = calculate_rmd_events({"401k": 500_000}, age=72, year=2026)
        assert events == []

    def test_single_account(self):
        events = calculate_rmd_events({"401k": 500_000}, age=75, year=2026)
        assert len(events) == 1
        assert events[0].name == "rmd"
        assert events[0].amount == pytest.approx(500_000 / 24.6)

    def test_multiple_accounts(self):
        balances = {"401k": 500_000, "trad_ira": 200_000}
        events = calculate_rmd_events(balances, age=75, year=2026)
        assert len(events) == 2

    def test_zero_balance_skipped(self):
        events = calculate_rmd_events({"401k": 0}, age=75, year=2026)
        assert events == []

    def test_first_rmd_metadata(self):
        events = calculate_rmd_events({"401k": 500_000}, age=73, year=2026)
        assert events[0].metadata["is_first_rmd"] is True
        assert events[0].metadata["can_delay_to_april"] is True

    def test_month_12(self):
        events = calculate_rmd_events({"401k": 500_000}, age=75, year=2026)
        assert events[0].month == 12


class TestProcessYearEvents:

    def test_empty_year(self):
        events = process_year_events(
            year=2026, age=35, magi=100_000, magi_two_years_prior=80_000,
            irmaa_annual=0, aca_annual_subsidy=0, aca_months_eligible=0,
            pre_tax_balances={},
        )
        assert events == []

    def test_mixed_events(self):
        events = process_year_events(
            year=2026, age=75, magi=300_000, magi_two_years_prior=280_000,
            irmaa_annual=4_800, aca_annual_subsidy=0, aca_months_eligible=0,
            pre_tax_balances={"401k": 500_000},
        )
        # 12 IRMAA + 1 RMD = 13 events
        assert len(events) == 13
        names = {e.name for e in events}
        assert "irmaa_surcharge" in names
        assert "rmd" in names

    def test_events_sorted_by_month(self):
        events = process_year_events(
            year=2026, age=75, magi=300_000, magi_two_years_prior=280_000,
            irmaa_annual=4_800, aca_annual_subsidy=12_000, aca_months_eligible=12,
            pre_tax_balances={"401k": 500_000},
        )
        months = [e.month for e in events]
        assert months == sorted(months)
