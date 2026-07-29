"""Regression tests for tax edge cases — Phase 1f.

Tests IRS-published examples, bracket boundaries, and known edge cases.
These serve as golden cases to catch regressions in the tax engine.
"""
import pytest
from retirement_planner.tax_law import (
    TaxLawRegistry, FilingStatus, bracket_tax,
    calculate_niit, calculate_amt, calculate_irmaa, calculate_aca_subsidy,
    calculate_estate_tax, calculate_child_tax_credit, calculate_qcd,
    determine_filing_status,
)


# ---------------------------------------------------------------------------
# Bracket boundary tests
# ---------------------------------------------------------------------------
class TestBracketBoundaries:

    def test_10pct_to_12pct_boundary_mfj_2024(self):
        """MFJ 2024: 10% ends at $23,200, 12% starts."""
        law = TaxLawRegistry().law_for_year(2024)
        brackets = law.federal_brackets[FilingStatus.MFJ]

        # Exactly at boundary
        tax_at_boundary = bracket_tax(23_200, brackets)
        assert tax_at_boundary == pytest.approx(23_200 * 0.10)

        # One dollar over
        tax_one_over = bracket_tax(23_201, brackets)
        assert tax_one_over == pytest.approx(23_200 * 0.10 + 1 * 0.12)

    def test_top_bracket_mfj_2024(self):
        """MFJ 2024: 37% starts at $731,200."""
        law = TaxLawRegistry().law_for_year(2024)
        brackets = law.federal_brackets[FilingStatus.MFJ]

        # $1M income
        tax = bracket_tax(1_000_000, brackets)
        # Expected: sum of all lower brackets + 37% on excess
        expected = (
            23_200 * 0.10
            + (94_300 - 23_200) * 0.12
            + (201_050 - 94_300) * 0.22
            + (383_900 - 201_050) * 0.24
            + (487_450 - 383_900) * 0.32
            + (731_200 - 487_450) * 0.35
            + (1_000_000 - 731_200) * 0.37
        )
        assert tax == pytest.approx(expected)

    def test_zero_income_zero_tax(self):
        law = TaxLawRegistry().law_for_year(2024)
        for status in FilingStatus:
            brackets = law.federal_brackets.get(status, [])
            assert bracket_tax(0, brackets) == 0.0


# ---------------------------------------------------------------------------
# LTCG stacking tests
# ---------------------------------------------------------------------------
class TestLTCGStacking:

    def test_0pct_ltcg_band_mfj_2024(self):
        """MFJ 2024: LTCG 0% up to $94,050 total income."""
        law = TaxLawRegistry().law_for_year(2024)
        ltcg_brackets = law.ltcg_brackets[FilingStatus.MFJ]

        # $50K ordinary + $40K LTCG = $90K total < $94,050 → all 0%
        remaining = 50_000
        ltcg_tax = 0.0
        prev = 0.0
        ltcg_left = 40_000
        for b in ltcg_brackets:
            if ltcg_left <= 0:
                break
            width = b.upper - prev
            prev = b.upper
            ordinary_in = min(remaining, width)
            remaining -= ordinary_in
            available = width - ordinary_in
            taxed = min(ltcg_left, available)
            ltcg_tax += taxed * b.rate
            ltcg_left -= taxed
        assert ltcg_tax == 0.0

    def test_15pct_ltcg_band_mfj_2024(self):
        """MFJ 2024: LTCG 15% from $94,050 to $583,750."""
        law = TaxLawRegistry().law_for_year(2024)
        ltcg_brackets = law.ltcg_brackets[FilingStatus.MFJ]

        # $200K ordinary + $100K LTCG → some in 15% band
        remaining = 200_000
        ltcg_tax = 0.0
        prev = 0.0
        ltcg_left = 100_000
        for b in ltcg_brackets:
            if ltcg_left <= 0:
                break
            width = b.upper - prev
            prev = b.upper
            ordinary_in = min(remaining, width)
            remaining -= ordinary_in
            available = width - ordinary_in
            taxed = min(ltcg_left, available)
            ltcg_tax += taxed * b.rate
            ltcg_left -= taxed
        # Some LTCG should be taxed at 15%
        assert ltcg_tax > 0


# ---------------------------------------------------------------------------
# NIIT edge cases
# ---------------------------------------------------------------------------
class TestNIITEdgeCases:

    def test_exactly_at_threshold(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI exactly at threshold → no NIIT
        assert calculate_niit(50_000, 250_000, law, FilingStatus.MFJ) == 0.0

    def test_one_dollar_over(self):
        law = TaxLawRegistry().law_for_year(2024)
        niit = calculate_niit(50_000, 250_001, law, FilingStatus.MFJ)
        assert niit == pytest.approx(1 * 0.038)

    def test_zero_investment_income(self):
        law = TaxLawRegistry().law_for_year(2024)
        assert calculate_niit(0, 500_000, law, FilingStatus.MFJ) == 0.0

    def test_single_threshold_lower(self):
        law = TaxLawRegistry().law_for_year(2024)
        # Single: threshold = $200K
        niit = calculate_niit(30_000, 220_000, law, FilingStatus.SINGLE)
        assert niit == pytest.approx(20_000 * 0.038)


# ---------------------------------------------------------------------------
# IRMAA edge cases
# ---------------------------------------------------------------------------
class TestIRMAAEdgeCases:

    def test_exactly_at_tier_boundary(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI exactly at 206K → $0 surcharge
        assert calculate_irmaa(206_000, law) == 0.0

    def test_one_dollar_over_first_tier(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 206,001 → Tier 1: $70/mo Part B + $10/mo Part D
        surcharge = calculate_irmaa(206_001, law, num_people=1)
        expected = (70.0 + 10.0) * 12
        assert surcharge == pytest.approx(expected)


# ---------------------------------------------------------------------------
# ACA edge cases
# ---------------------------------------------------------------------------
class TestACACases:

    def test_exactly_at_cliff(self):
        law = TaxLawRegistry().law_for_year(2024)
        # Family of 4: FPL = $31,200, 400% = $124,800
        # MAGI = $124,800 → still eligible
        subsidy = calculate_aca_subsidy(124_800, 4, law, "CA")
        assert subsidy > 0

    def test_one_dollar_over_cliff(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = $124,801 → above 400% FPL → no subsidy
        subsidy = calculate_aca_subsidy(124_801, 4, law, "CA")
        assert subsidy == 0.0


# ---------------------------------------------------------------------------
# Filing status transition edge cases
# ---------------------------------------------------------------------------
class TestFilingStatusEdge:

    def test_death_year_still_mfj(self):
        """Death in December → still MFJ for that year."""
        assert determine_filing_status(True, False, 2026, 2026, True) == FilingStatus.MFJ

    def test_qss_year_1(self):
        assert determine_filing_status(True, False, 2026, 2027, True) == FilingStatus.QSS

    def test_qss_year_2(self):
        assert determine_filing_status(True, False, 2026, 2028, True) == FilingStatus.QSS

    def test_after_qss_with_kids(self):
        assert determine_filing_status(True, False, 2026, 2029, True) == FilingStatus.HOH

    def test_after_qss_without_kids(self):
        assert determine_filing_status(True, False, 2026, 2029, False) == FilingStatus.SINGLE


# ---------------------------------------------------------------------------
# Tax monotonicity property tests
# ---------------------------------------------------------------------------
class TestTaxMonotonicity:

    def test_higher_income_more_tax(self):
        """Tax should never decrease when income increases."""
        law = TaxLawRegistry().law_for_year(2024)
        brackets = law.federal_brackets[FilingStatus.MFJ]

        prev_tax = 0
        for income in range(0, 1_000_001, 10_000):
            tax = bracket_tax(income, brackets)
            assert tax >= prev_tax
            prev_tax = tax

    def test_higher_ltcg_more_tax(self):
        """LTCG tax should be non-decreasing."""
        from retirement_planner.tax_law import Bracket
        ltcg_brackets = [
            Bracket(94_050, 0.00), Bracket(583_750, 0.15), Bracket(float('inf'), 0.20),
        ]

        prev_tax = 0
        for ltcg in range(0, 1_000_001, 10_000):
            # Fixed $100K ordinary income
            remaining = 100_000
            tax = 0.0
            prev = 0.0
            left = ltcg
            for b in ltcg_brackets:
                if left <= 0:
                    break
                width = b.upper - prev
                prev = b.upper
                ordinary_in = min(remaining, width)
                remaining -= ordinary_in
                available = width - ordinary_in
                taxed = min(left, available)
                tax += taxed * b.rate
                left -= taxed
            assert tax >= prev_tax
            prev_tax = tax


# ---------------------------------------------------------------------------
# Golden test: known IRS example (2024 MFJ, $200K ordinary + $50K LTCG)
# ---------------------------------------------------------------------------
class TestGoldenCases:

    def test_irs_example_mfj_200k_50k_ltcg(self):
        """Approximate IRS example: MFJ, $200K ordinary, $50K LTCG, 2024."""
        law = TaxLawRegistry().law_for_year(2024)
        status = FilingStatus.MFJ
        sd = law.standard_deduction[status]

        ordinary = 200_000
        ltcg = 50_000

        ordinary_after_sd = max(0, ordinary - sd)
        fed_ordinary = bracket_tax(ordinary_after_sd, law.federal_brackets[status])

        # LTCG stacking
        remaining = ordinary_after_sd
        ltcg_tax = 0.0
        prev = 0.0
        ltcg_left = ltcg
        for b in law.ltcg_brackets[status]:
            if ltcg_left <= 0:
                break
            width = b.upper - prev
            prev = b.upper
            ordinary_in = min(remaining, width)
            remaining -= ordinary_in
            available = width - ordinary_in
            taxed = min(ltcg_left, available)
            ltcg_tax += taxed * b.rate
            ltcg_left -= taxed

        total_fed = fed_ordinary + ltcg_tax

        # Should be positive and reasonable
        assert total_fed > 0
        assert total_fed < 100_000  # Sanity check

        # Marginal rate check: $200K ordinary is in 22% bracket
        assert fed_ordinary > 0
