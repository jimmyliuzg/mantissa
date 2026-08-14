"""Tests for tax_law.py — versioned tax-law registry and calculations."""
import pytest
from retirement_planner.tax_law import (
    TaxLawVersion, TaxLawRegistry, FilingStatus, Bracket,
    bracket_tax, calculate_niit, calculate_amt, calculate_irmaa,
    calculate_aca_subsidy, calculate_estate_tax, estate_tax_on_taxable,
    calculate_child_tax_credit, calculate_qcd, determine_filing_status,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
class TestTaxLawRegistry:

    def test_has_2024_2025_2026(self):
        reg = TaxLawRegistry()
        years = reg.available_years()
        assert 2024 in years
        assert 2025 in years
        assert 2026 in years

    def test_law_for_exact_year(self):
        reg = TaxLawRegistry()
        law = reg.law_for_year(2024)
        assert law.year == 2024
        assert law.name == "2024 Enacted (TCJA/OBBBA)"

    def test_law_for_future_year_inflates(self):
        reg = TaxLawRegistry()
        law_2026 = reg.law_for_year(2026)
        law_2030 = reg.law_for_year(2030, fallback_inflation=0.025)
        # Standard deduction should be inflated from 2026 base
        sd_2026 = law_2026.standard_deduction[FilingStatus.MFJ]
        sd_2030 = law_2030.standard_deduction[FilingStatus.MFJ]
        assert sd_2030 > sd_2026
        # Should be ~1.104x (1.025^4)
        assert sd_2030 == pytest.approx(sd_2026 * 1.025**4, rel=1e-3)

    def test_law_for_unknown_year_uses_nearest_base(self):
        reg = TaxLawRegistry()
        law = reg.law_for_year(2027, fallback_inflation=0.03)
        assert law.year == 2027
        assert "inflated" in law.name.lower()

    def test_register_custom_law(self):
        reg = TaxLawRegistry()
        custom = TaxLawVersion(
            year=2030, name="Custom 2030",
            federal_brackets={}, standard_deduction={},
            ltcg_brackets={}, niit_thresholds={},
        )
        reg.register(custom)
        assert reg.law_for_year(2030).name == "Custom 2030"

    def test_alternative_scenario_raises(self):
        reg = TaxLawRegistry()
        with pytest.raises(ValueError, match="not yet implemented"):
            reg.law_for_year(2024, policy_scenario="alternative_sunset")


# ---------------------------------------------------------------------------
# Bracket tax
# ---------------------------------------------------------------------------
class TestBracketTax:

    def test_zero_income(self):
        brackets = [Bracket(10_000, 0.10), Bracket(float('inf'), 0.22)]
        assert bracket_tax(0, brackets) == 0.0

    def test_single_bracket(self):
        brackets = [Bracket(10_000, 0.10), Bracket(float('inf'), 0.22)]
        assert bracket_tax(5_000, brackets) == 500.0

    def test_two_brackets(self):
        brackets = [Bracket(10_000, 0.10), Bracket(float('inf'), 0.22)]
        assert bracket_tax(15_000, brackets) == pytest.approx(1_000 + 5_000 * 0.22)

    def test_exact_bracket_boundary(self):
        brackets = [Bracket(10_000, 0.10), Bracket(float('inf'), 0.22)]
        assert bracket_tax(10_000, brackets) == 1_000.0

    def test_top_bracket(self):
        brackets = [Bracket(10_000, 0.10), Bracket(float('inf'), 0.37)]
        assert bracket_tax(1_000_000, brackets) == pytest.approx(1_000 + 990_000 * 0.37)


# ---------------------------------------------------------------------------
# NIIT
# ---------------------------------------------------------------------------
class TestNIIT:

    def test_below_threshold(self):
        law = TaxLawRegistry().law_for_year(2024)
        assert calculate_niit(50_000, 200_000, law, FilingStatus.MFJ) == 0.0

    def test_above_threshold(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 300K, threshold = 250K, excess = 50K
        # NII = 60K, so taxed on min(60K, 50K) = 50K
        niit = calculate_niit(60_000, 300_000, law, FilingStatus.MFJ)
        assert niit == pytest.approx(50_000 * 0.038)

    def test_nii_less_than_excess(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 400K, threshold = 250K, excess = 150K
        # NII = 30K, so taxed on min(30K, 150K) = 30K
        niit = calculate_niit(30_000, 400_000, law, FilingStatus.MFJ)
        assert niit == pytest.approx(30_000 * 0.038)


# ---------------------------------------------------------------------------
# AMT
# ---------------------------------------------------------------------------
class TestAMT:

    def test_no_amt_when_regular_tax_high(self):
        law = TaxLawRegistry().law_for_year(2024)
        amt = calculate_amt(
            regular_tax=100_000,
            tax_inputs_ordinary=300_000,
            tax_inputs_ltcg=0,
            law=law,
            status=FilingStatus.MFJ,
        )
        assert amt == 0.0

    def test_amt_when_low_regular_tax(self):
        law = TaxLawRegistry().law_for_year(2024)
        # Low regular tax, high AMTI → AMT triggers
        amt = calculate_amt(
            regular_tax=5_000,
            tax_inputs_ordinary=500_000,
            tax_inputs_ltcg=0,
            law=law,
            status=FilingStatus.MFJ,
        )
        assert amt > 0


# ---------------------------------------------------------------------------
# IRMAA
# ---------------------------------------------------------------------------
class TestIRMAA:

    def test_no_surcharge_below_threshold(self):
        law = TaxLawRegistry().law_for_year(2024)
        surcharge = calculate_irmaa(200_000, law, num_people=2)
        assert surcharge == 0.0

    def test_surcharge_above_threshold(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 270K → Tier 2 (258K-322K): $175/mo Part B + $26/mo Part D
        surcharge = calculate_irmaa(270_000, law, num_people=2)
        expected = (175.0 + 26.0) * 12 * 2
        assert surcharge == pytest.approx(expected)

    def test_high_tier_surcharge(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 800K → Tier 6: $587/mo Part B + $77/mo Part D
        surcharge = calculate_irmaa(800_000, law, num_people=2)
        expected = (587.0 + 77.0) * 12 * 2
        assert surcharge == pytest.approx(expected)


# ---------------------------------------------------------------------------
# ACA subsidy
# ---------------------------------------------------------------------------
class TestACASubsidy:

    def test_no_subsidy_above_cliff(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 200K for family of 4 → >400% FPL
        subsidy = calculate_aca_subsidy(200_000, 4, law, "CA")
        assert subsidy == 0.0

    def test_subsidy_below_cliff(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = 60K for family of 4 → ~192% FPL → 4.0% applicable
        subsidy = calculate_aca_subsidy(60_000, 4, law, "CA")
        assert subsidy > 0

    def test_zero_income_full_subsidy(self):
        law = TaxLawRegistry().law_for_year(2024)
        subsidy = calculate_aca_subsidy(0, 4, law, "CA")
        # Full benchmark premium should be covered
        assert subsidy > 0


# ---------------------------------------------------------------------------
# Estate tax
# ---------------------------------------------------------------------------
class TestEstateTax:

    def test_below_exemption(self):
        law = TaxLawRegistry().law_for_year(2024)
        tax = calculate_estate_tax(10_000_000, law, FilingStatus.MFJ)
        assert tax == 0.0

    def test_above_exemption(self):
        law = TaxLawRegistry().law_for_year(2024)
        # $30M estate, $27.22M exemption → $2.78M taxable at progressive
        # IRC §2001(c) rates (18% first $10K … 40% above $1M).
        tax = calculate_estate_tax(30_000_000, law, FilingStatus.MFJ)
        taxable = 30_000_000 - 27_220_000
        assert tax < taxable * 0.40  # progressive beats flat 40%
        assert tax == pytest.approx(estate_tax_on_taxable(taxable))


# ---------------------------------------------------------------------------
# Child tax credit
# ---------------------------------------------------------------------------
class TestChildTaxCredit:

    def test_no_children(self):
        law = TaxLawRegistry().law_for_year(2024)
        assert calculate_child_tax_credit(0, 100_000, law) == 0.0

    def test_two_children_below_phaseout(self):
        law = TaxLawRegistry().law_for_year(2024)
        credit = calculate_child_tax_credit(2, 100_000, law, FilingStatus.MFJ)
        assert credit == 4_000

    def test_phaseout(self):
        law = TaxLawRegistry().law_for_year(2024)
        # MAGI = $410K, threshold = $400K → excess = $10K
        # Phaseout: (10_000 // 1_000 + 1) × $50 = 11 × $50 = $550 reduction
        credit = calculate_child_tax_credit(2, 410_000, law, FilingStatus.MFJ)
        assert credit == pytest.approx(4_000 - 550)


# ---------------------------------------------------------------------------
# QCD
# ---------------------------------------------------------------------------
class TestQCD:

    def test_too_young(self):
        law = TaxLawRegistry().law_for_year(2024)
        assert calculate_qcd(100_000, 65, True, law) == 0.0

    def test_old_enough(self):
        law = TaxLawRegistry().law_for_year(2024)
        qcd = calculate_qcd(100_000, 75, True, law)
        assert qcd == 100_000  # under limit

    def test_not_charitably_inclined(self):
        law = TaxLawRegistry().law_for_year(2024)
        assert calculate_qcd(100_000, 75, False, law) == 0.0

    def test_qcd_capped(self):
        law = TaxLawRegistry().law_for_year(2024)
        qcd = calculate_qcd(500_000, 80, True, law)
        assert qcd == pytest.approx(105_000 * law.inflation_factor)


# ---------------------------------------------------------------------------
# Filing status transitions
# ---------------------------------------------------------------------------
class TestFilingStatus:

    def test_both_alive(self):
        assert determine_filing_status(True, True, None, 2024, True) == FilingStatus.MFJ

    def test_death_year(self):
        assert determine_filing_status(True, False, 2024, 2024, True) == FilingStatus.MFJ

    def test_qss_with_dependents(self):
        assert determine_filing_status(True, False, 2024, 2025, True) == FilingStatus.QSS
        assert determine_filing_status(True, False, 2024, 2026, True) == FilingStatus.QSS

    def test_after_qss_with_dependents(self):
        assert determine_filing_status(True, False, 2024, 2027, True) == FilingStatus.HOH

    def test_after_qss_without_dependents(self):
        assert determine_filing_status(True, False, 2024, 2027, False) == FilingStatus.SINGLE


# ---------------------------------------------------------------------------
# Inflation indexing consistency
# ---------------------------------------------------------------------------
class TestInflationIndexing:

    def test_brackets_increase_with_year(self):
        reg = TaxLawRegistry()
        for y in [2024, 2025, 2026]:
            law = reg.law_for_year(y)
            sd = law.standard_deduction[FilingStatus.MFJ]
            if y > 2024:
                prev_sd = reg.law_for_year(y - 1).standard_deduction[FilingStatus.MFJ]
                assert sd >= prev_sd

    def test_ltcg_0_percent_bracket_increases(self):
        reg = TaxLawRegistry()
        for y in [2024, 2025, 2026]:
            law = reg.law_for_year(y)
            ltcg_0 = law.ltcg_brackets[FilingStatus.MFJ][0].upper
            if y > 2024:
                prev = reg.law_for_year(y - 1).ltcg_brackets[FilingStatus.MFJ][0].upper
                assert ltcg_0 >= prev
