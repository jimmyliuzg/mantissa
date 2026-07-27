"""Tests for the historical market return data module."""
import pytest

from retirement_planner.historical_data import (
    HISTORICAL_BOND_REAL_RETURNS,
    HISTORICAL_SNP500_REAL_RETURNS,
    HISTORICAL_YEARS,
    _HISTORICAL_BOND_VALUES,
    _HISTORICAL_SNP500_VALUES,
    get_historical_return,
    get_historical_sequence,
)


# ---------------------------------------------------------------------------
# Coverage / data integrity
# ---------------------------------------------------------------------------
def test_historical_years_cover_1926_to_2023():
    assert HISTORICAL_YEARS == list(range(1926, 2024))
    assert HISTORICAL_YEARS[0] == 1926
    assert HISTORICAL_YEARS[-1] == 2023
    assert len(HISTORICAL_YEARS) == 98


def test_snp500_values_length_matches_years():
    assert len(_HISTORICAL_SNP500_VALUES) == len(HISTORICAL_YEARS)
    assert len(HISTORICAL_SNP500_REAL_RETURNS) == len(HISTORICAL_YEARS)


def test_bond_values_length_matches_years():
    assert len(_HISTORICAL_BOND_VALUES) == len(HISTORICAL_YEARS)
    assert len(HISTORICAL_BOND_REAL_RETURNS) == len(HISTORICAL_YEARS)


# ---------------------------------------------------------------------------
# get_historical_return — known years
# ---------------------------------------------------------------------------
def test_1929_crash_is_negative():
    r = get_historical_return(1929)
    assert r == pytest.approx(-0.312)
    assert r < 0


def test_1933_recovery_is_positive():
    r = get_historical_return(1933)
    assert r == pytest.approx(0.540)
    assert r > 0


def test_2008_gfc_is_negative():
    assert get_historical_return(2008) == pytest.approx(-0.370)


def test_returns_within_reasonable_bounds():
    # Real S&P 500 annual returns historically stay within -50% / +60%
    for year in HISTORICAL_YEARS:
        r = get_historical_return(year)
        assert -0.60 < r < 0.70, f"year {year} return {r} out of bounds"


def test_bond_returns_have_low_volatility():
    for year in HISTORICAL_YEARS:
        r = get_historical_return(year, asset_class="bond")
        assert -0.05 < r < 0.08, f"year {year} bond return {r} out of bounds"


def test_year_wraps_cyclically():
    # 2024 wraps to 1926, 2025 -> 1927, etc.
    assert get_historical_return(2024) == get_historical_return(1926)
    assert get_historical_return(2025) == get_historical_return(1927)
    # Years before 1926 wrap from the end
    assert get_historical_return(1925) == get_historical_return(2023)


def test_unknown_asset_class_defaults_to_equity():
    assert get_historical_return(2000, asset_class="other") == \
        get_historical_return(2000, asset_class="equity")


# ---------------------------------------------------------------------------
# get_historical_sequence
# ---------------------------------------------------------------------------
def test_sequence_returns_exactly_n_values():
    seq = get_historical_sequence(30, start_year_index=0)
    assert len(seq) == 30


def test_sequence_matches_underlying_data():
    seq = get_historical_sequence(10, start_year_index=0)
    assert seq == _HISTORICAL_SNP500_VALUES[:10]
    assert seq[0] == pytest.approx(HISTORICAL_SNP500_REAL_RETURNS[1926])


def test_sequence_wraps_when_n_exceeds_data():
    span = len(_HISTORICAL_SNP500_VALUES)
    seq = get_historical_sequence(span + 5, start_year_index=0)
    assert len(seq) == span + 5
    # After exhausting data, it wraps to the beginning
    assert seq[span] == _HISTORICAL_SNP500_VALUES[0]
    assert seq[span + 4] == _HISTORICAL_SNP500_VALUES[4]


def test_sequence_random_start_returns_n_values():
    seq = get_historical_sequence(25)  # start_year_index=None → random
    assert len(seq) == 25
    assert all(isinstance(r, float) for r in seq)


def test_sequence_bond_asset_class():
    seq = get_historical_sequence(5, start_year_index=0, asset_class="bond")
    assert seq == _HISTORICAL_BOND_VALUES[:5]
