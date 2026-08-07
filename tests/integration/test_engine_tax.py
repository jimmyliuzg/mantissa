"""Known-answer tests for engine tax calculations."""
from datetime import date

import pytest

from retirement_planner.engine import RetirementPlanner
from retirement_planner.tax_law import (
    TaxLawRegistry, FilingStatus, bracket_tax,
)
from retirement_planner.models import (
    EconomicAssumptions, Person, Scenario, TaxableIncome,
)

# Get 2024 brackets from registry
_registry = TaxLawRegistry()
_law_2024 = _registry.law_for_year(2024)
_FEDERAL_BRACKETS_TUPLE = [(b.upper, b.rate) for b in _law_2024.federal_brackets[FilingStatus.MFJ]]
_CA_BRACKETS_TUPLE = [(b.upper, b.rate) for b in _law_2024.ca_brackets]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _make_planner() -> RetirementPlanner:
    """Minimal planner — tax methods only need a valid Scenario shell."""
    person_kwargs = dict(
        birth_date=date(1970, 1, 1),
        retirement_date=date(2030, 1, 1),
        longevity_age=90,
    )
    scenario = Scenario(
        name="Tax Test",
        description="",
        primary=Person(name="Primary", **person_kwargs),
        spouse=Person(name="Spouse", **person_kwargs),
        economic=EconomicAssumptions(),
        accounts=[],
        income_streams=[],
        expenses=[],
        mortgages=[],
        state="CA",
    )
    return RetirementPlanner(scenario)


@pytest.fixture
def planner():
    return _make_planner()


# 2024 Single filer ordinary brackets (for testing _bracket_tax generality)
_SINGLE_BRACKETS = [
    (11_600, 0.10),
    (47_150, 0.12),
    (100_525, 0.22),
    (191_950, 0.24),
    (243_725, 0.32),
    (609_350, 0.35),
    (float("inf"), 0.37),
]
_SINGLE_STD_DEDUCTION = 14_600


# ---------------------------------------------------------------------------
# Federal tax — MFJ (known answers, 2024 brackets, no inflation indexing)
# ---------------------------------------------------------------------------
def test_federal_mfj_100k_ordinary(planner):
    """$100K ordinary income, MFJ: std deduction $29,200 → $70,800 taxable.

    Federal: 23,200@10% + 47,600@12% = 2,320 + 5,712 = 8,032
    CA:      20,824@1% + 28,544@2% + 21,432@4% = 208.24 + 570.88 + 857.28
             = 1,636.40
    Total:   9,668.40
    """
    income = TaxableIncome(ordinary=100_000, capital_gains=0, tax_free=0,
                           total=100_000)
    tax = planner.calculate_taxes(2024, income, inflation_rate=0.0,
                                  years_from_base=0)
    assert tax == pytest.approx(9_668.40, abs=0.01)


def test_federal_mfj_zero_income(planner):
    income = TaxableIncome(ordinary=0, capital_gains=0, tax_free=0, total=0)
    tax = planner.calculate_taxes(2024, income, inflation_rate=0.0,
                                  years_from_base=0)
    assert tax == 0.0


def test_federal_mfj_below_standard_deduction(planner):
    """Income below the $29,200 standard deduction owes nothing."""
    income = TaxableIncome(ordinary=25_000, capital_gains=0, tax_free=0,
                           total=25_000)
    tax = planner.calculate_taxes(2024, income, inflation_rate=0.0,
                                  years_from_base=0)
    assert tax == 0.0


def test_federal_mfj_bracket_math_only():
    """_bracket_tax on MFJ schedule: $70,800 taxable → $8,032."""
    tax = bracket_tax(70_800, _FEDERAL_BRACKETS_TUPLE)
    assert tax == pytest.approx(8_032.00, abs=0.01)


# ---------------------------------------------------------------------------
# Federal tax — Single filer (bracket math via _bracket_tax)
# ---------------------------------------------------------------------------
def test_federal_single_100k():
    """$100K income, Single: $14,600 std deduction → $85,400 taxable.

    11,600@10% + 35,550@12% + 38,250@22%
    = 1,160 + 4,266 + 8,415 = 13,841
    """
    taxable = 100_000 - _SINGLE_STD_DEDUCTION
    tax = bracket_tax(taxable, _SINGLE_BRACKETS)
    assert tax == pytest.approx(13_841.00, abs=0.01)


def test_federal_single_low_income():
    """$20,000 income, Single → $5,400 taxable, all in 10% bracket."""
    taxable = 20_000 - _SINGLE_STD_DEDUCTION
    tax = bracket_tax(taxable, _SINGLE_BRACKETS)
    assert tax == pytest.approx(540.00, abs=0.01)


# ---------------------------------------------------------------------------
# California state tax (known answer)
# ---------------------------------------------------------------------------
def test_ca_tax_100k():
    """CA tax on $70,800 taxable (100K - 29,200 std deduction):

    20,824@1% + 28,544@2% + 21,432@4%
    = 208.24 + 570.88 + 857.28 = 1,636.40
    """
    tax = bracket_tax(70_800, _CA_BRACKETS_TUPLE)
    assert tax == pytest.approx(1_636.40, abs=0.01)


# ---------------------------------------------------------------------------
# Marginal rate at bracket boundary
# ---------------------------------------------------------------------------
def test_marginal_rate_at_bracket_boundary():
    """Crossing the $94,300 MFJ boundary: 12% below, 22% above."""
    at_boundary = bracket_tax(94_300, _FEDERAL_BRACKETS_TUPLE)
    just_below = bracket_tax(94_299, _FEDERAL_BRACKETS_TUPLE)
    just_above = bracket_tax(94_301, _FEDERAL_BRACKETS_TUPLE)

    assert at_boundary - just_below == pytest.approx(0.12, abs=1e-9)
    assert just_above - at_boundary == pytest.approx(0.22, abs=1e-9)


def test_marginal_rate_first_boundary():
    """Crossing $23,200: 10% below, 12% above."""
    at = bracket_tax(23_200, _FEDERAL_BRACKETS_TUPLE)
    assert at - bracket_tax(23_199, _FEDERAL_BRACKETS_TUPLE) == pytest.approx(0.10)
    assert bracket_tax(23_201, _FEDERAL_BRACKETS_TUPLE) - at == pytest.approx(0.12)


# ---------------------------------------------------------------------------
# End-to-end calculate_taxes with mixed income types
# ---------------------------------------------------------------------------
def test_calculate_taxes_mixed_income(planner):
    """$50K ordinary + $100K LTCG, no inflation indexing.

    Federal ordinary: (50,000 - 29,200) = 20,800 @10%        = 2,080.00
    Federal LTCG: 0% bracket has 94,050 - 20,800 = 73,250 room;
                  remaining 26,750 @15%                       = 4,012.50
    CA (all ordinary): 150,000 - 29,200 = 120,800 taxable     = 4,747.00
    Total:                                                      10,839.50
    """
    income = TaxableIncome(ordinary=50_000, capital_gains=100_000,
                           tax_free=0, total=150_000)
    tax = planner.calculate_taxes(2024, income, inflation_rate=0.0,
                                  years_from_base=0)
    assert tax == pytest.approx(10_839.50, abs=0.01)


def test_calculate_taxes_inflation_indexing_lowers_tax(planner):
    """Indexing brackets to inflation raises thresholds → lower tax."""
    income = TaxableIncome(ordinary=100_000, capital_gains=0, tax_free=0,
                           total=100_000)
    tax_base = planner.calculate_taxes(2024, income, inflation_rate=0.0,
                                       years_from_base=0)
    tax_indexed = planner.calculate_taxes(2034, income, inflation_rate=0.025,
                                          years_from_base=10)
    assert tax_indexed < tax_base


def test_calculate_taxes_roth_withdrawal_not_taxed(planner):
    """Tax-free (Roth) income must not appear in the tax bill."""
    income = TaxableIncome(ordinary=0, capital_gains=0, tax_free=200_000,
                           total=200_000)
    tax = planner.calculate_taxes(2024, income, inflation_rate=0.0,
                                  years_from_base=0)
    assert tax == 0.0
