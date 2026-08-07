"""Tests for sim_integration.py — filing status, GBM, contribution limits."""
import pytest
from retirement_planner.sim_integration import (
    determine_annual_filing_status, compute_survivor_ss_benefit,
    GBMParams, simulate_gbm_path, simulate_rsu_value,
    get_contribution_limits,
    calculate_401k_limit, calculate_ira_limit, calculate_hsa_limit,
)


# ---------------------------------------------------------------------------
# Filing status
# ---------------------------------------------------------------------------
class TestFilingStatus:

    def test_both_alive(self):
        assert determine_annual_filing_status(
            2026, True, True, None, False) == "MFJ"

    def test_death_year_still_mfj(self):
        assert determine_annual_filing_status(
            2040, True, False, 2040, False) == "MFJ"

    def test_qss_year1(self):
        assert determine_annual_filing_status(
            2041, True, False, 2040, True) == "QSS"

    def test_qss_year2(self):
        assert determine_annual_filing_status(
            2042, True, False, 2040, True) == "QSS"

    def test_after_qss_with_kids(self):
        assert determine_annual_filing_status(
            2043, True, False, 2040, True) == "HOH"

    def test_after_qss_without_kids(self):
        assert determine_annual_filing_status(
            2043, True, False, 2040, False) == "SINGLE"


# ---------------------------------------------------------------------------
# Survivor SS
# ---------------------------------------------------------------------------
class TestSurvivorSS:

    def test_both_alive(self):
        assert compute_survivor_ss_benefit(30000, 20000, True, True) == 50000

    def test_spouse_dies_higher_benefit(self):
        # Spouse had higher benefit — survivor gets spouse's
        assert compute_survivor_ss_benefit(20000, 30000, True, False) == 30000

    def test_spouse_dies_lower_benefit(self):
        # Primary had higher benefit — survivor keeps own
        assert compute_survivor_ss_benefit(30000, 20000, True, False) == 30000

    def test_primary_dies(self):
        # Primary had higher benefit — spouse gets primary's
        assert compute_survivor_ss_benefit(30000, 20000, False, True) == 30000


# ---------------------------------------------------------------------------
# GBM pricing
# ---------------------------------------------------------------------------
class TestGBM:

    def test_path_length(self):
        params = GBMParams(initial_price=100.0, mu=0.08, sigma=0.35)
        prices = simulate_gbm_path(params, years=10, seed=42)
        assert len(prices) == 11  # t=0 through t=10

    def test_initial_price(self):
        params = GBMParams(initial_price=100.0)
        prices = simulate_gbm_path(params, years=5, seed=42)
        assert prices[0] == 100.0

    def test_reproducible_with_seed(self):
        params = GBMParams(initial_price=100.0)
        p1 = simulate_gbm_path(params, years=10, seed=42)
        p2 = simulate_gbm_path(params, years=10, seed=42)
        assert p1 == p2

    def test_prices_positive(self):
        params = GBMParams(initial_price=100.0, sigma=0.5)
        prices = simulate_gbm_path(params, years=20, seed=42)
        assert all(p > 0 for p in prices)

    def test_expected_direction(self):
        # With positive mu, mean should be positive drift
        params = GBMParams(initial_price=100.0, mu=0.08, sigma=0.01)
        prices = simulate_gbm_path(params, years=10, seed=42)
        # Low vol, should drift up
        assert prices[-1] > prices[0]


class TestRSUValue:

    def test_flat_price(self):
        values = simulate_rsu_value(100, [0, 175, 175, 175], sell_fraction=1.0)
        assert values[0] == 0
        assert values[1] == pytest.approx(17_500)

    def test_varying_price(self):
        prices = [0, 100, 150, 200]
        values = simulate_rsu_value(100, prices)
        assert values[1] == 10_000
        assert values[2] == 15_000
        assert values[3] == 20_000

    def test_partial_sell(self):
        values = simulate_rsu_value(100, [0, 200], sell_fraction=0.5)
        assert values[1] == pytest.approx(10_000)  # 100 × 200 × 0.5


# ---------------------------------------------------------------------------
# Contribution limits
# ---------------------------------------------------------------------------
class TestContributionLimits:

    def test_2024_limits(self):
        limits = get_contribution_limits(2024)
        assert limits.elec_deferral_limit == 23_000
        assert limits.ira_limit == 7_000
        assert limits.hsa_family == 8_300

    def test_2025_limits(self):
        limits = get_contribution_limits(2025)
        assert limits.elec_deferral_limit == 23_500
        assert limits.hsa_family == 8_550

    def test_future_year_inflates(self):
        limits = get_contribution_limits(2030)
        assert limits.elec_deferral_limit > 23_500

    def test_401k_under_50(self):
        assert calculate_401k_limit(40, 2025) == 23_500

    def test_401k_age_50_plus(self):
        assert calculate_401k_limit(55, 2025) == 23_500 + 7_500

    def test_401k_super_catch_up_60_63(self):
        assert calculate_401k_limit(61, 2025) == 23_500 + 11_250

    def test_ira_low_income(self):
        limit = calculate_ira_limit(40, 2025, magi=100_000, has_workplace_plan=True)
        assert limit == 7_000

    def test_ira_high_income_phaseout(self):
        limit = calculate_ira_limit(40, 2025, magi=140_000,
                                     filing_status="MFJ", has_workplace_plan=True)
        assert 0 < limit < 7_000  # partially phased out

    def test_ira_very_high_income(self):
        limit = calculate_ira_limit(40, 2025, magi=150_000,
                                     filing_status="MFJ", has_workplace_plan=True)
        assert limit == 0  # fully phased out

    def test_hsa_family(self):
        assert calculate_hsa_limit(40, 2025, "family") == 8_550

    def test_hsa_catch_up(self):
        assert calculate_hsa_limit(56, 2025, "family") == 8_550 + 1_000
