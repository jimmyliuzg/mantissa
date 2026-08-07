"""Tests for explain.py — explainability, validation, reproducibility."""
import random
import pytest
from retirement_planner.explain import (
    TaxTrace, build_tax_trace, ThresholdWarning, check_thresholds,
    ReproducibilityMetadata, ScenarioDiff, compare_scenarios,
    ValidationResult, validate_projection,
)


# ---------------------------------------------------------------------------
# TaxTrace
# ---------------------------------------------------------------------------
class TestTaxTrace:

    def test_build_trace(self):
        trace = build_tax_trace(
            year=2026, ordinary_income=300_000, capital_gains=50_000,
            qcd_amount=0, standard_deduction=29_200, itemized_deduction=20_000,
            federal_ordinary_tax=45_000, ltcg_tax=7_500, niit=0, amt=0,
            federal_credits=4_000, state_tax=25_000,
        )
        assert trace.total_tax == pytest.approx(45_000 + 7_500 - 4_000 + 25_000)
        assert trace.effective_rate > 0
        assert trace.deduction_type == "standard"

    def test_itemized_when_better(self):
        trace = build_tax_trace(
            year=2026, ordinary_income=300_000, capital_gains=0,
            qcd_amount=0, standard_deduction=29_200, itemized_deduction=40_000,
            federal_ordinary_tax=45_000, ltcg_tax=0, niit=0, amt=0,
            federal_credits=0, state_tax=25_000,
        )
        assert trace.deduction_type == "itemized"
        assert trace.deduction_used == 40_000

    def test_qcd_reduces_agi(self):
        trace = build_tax_trace(
            year=2026, ordinary_income=300_000, capital_gains=0,
            qcd_amount=50_000, standard_deduction=29_200, itemized_deduction=0,
            federal_ordinary_tax=45_000, ltcg_tax=0, niit=0, amt=0,
            federal_credits=0, state_tax=25_000,
        )
        assert trace.agi == 250_000  # 300K - 50K QCD

    def test_niit_warning(self):
        trace = build_tax_trace(
            year=2026, ordinary_income=200_000, capital_gains=100_000,
            qcd_amount=0, standard_deduction=29_200, itemized_deduction=0,
            federal_ordinary_tax=30_000, ltcg_tax=15_000, niit=3_800, amt=0,
            federal_credits=0, state_tax=20_000,
        )
        assert any("NIIT" in w for w in trace.warnings)

    def test_explain_output(self):
        trace = build_tax_trace(
            year=2026, ordinary_income=300_000, capital_gains=50_000,
            qcd_amount=0, standard_deduction=29_200, itemized_deduction=0,
            federal_ordinary_tax=45_000, ltcg_tax=7_500, niit=0, amt=0,
            federal_credits=4_000, state_tax=25_000,
        )
        text = trace.explain()
        assert "2026" in text
        assert "300,000" in text
        assert "MFJ" in text


# ---------------------------------------------------------------------------
# Threshold warnings
# ---------------------------------------------------------------------------
class TestThresholdWarnings:

    def test_no_warnings_low_income(self):
        warnings = check_thresholds(magi=50_000, age=40, year=2026)
        assert len(warnings) == 0

    def test_aca_cliff_warning(self):
        warnings = check_thresholds(magi=122_000, age=50, year=2026, aca_cliff=124_800)
        aca = [w for w in warnings if w.threshold_type == "aca_cliff"]
        assert len(aca) == 1
        assert aca[0].severity == "warning"

    def test_aca_cliff_critical(self):
        warnings = check_thresholds(magi=130_000, age=50, year=2026, aca_cliff=124_800)
        aca = [w for w in warnings if w.threshold_type == "aca_cliff"]
        assert len(aca) == 1
        assert aca[0].severity == "critical"

    def test_irmaa_warning(self):
        warnings = check_thresholds(magi=255_000, age=70, year=2026)
        irmaa = [w for w in warnings if w.threshold_type == "irmaa_tier"]
        assert len(irmaa) >= 1

    def test_bracket_boundary(self):
        warnings = check_thresholds(magi=200_000, age=40, year=2026)
        bracket = [w for w in warnings if w.threshold_type == "bracket_top"]
        assert len(bracket) >= 1

    def test_no_irmaa_under_65(self):
        warnings = check_thresholds(magi=300_000, age=60, year=2026)
        irmaa = [w for w in warnings if w.threshold_type == "irmaa_tier"]
        assert len(irmaa) == 0


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
class TestReproducibility:

    def test_from_config(self):
        config = {"accounts": {"401k": 500000}, "income": 300000}
        meta = ReproducibilityMetadata.from_config(config)
        assert meta.rng_seed >= 0
        assert len(meta.config_hash) == 16
        assert meta.code_version == "0.2.0"

    def test_same_config_same_hash(self):
        config = {"a": 1, "b": 2}
        m1 = ReproducibilityMetadata.from_config(config)
        m2 = ReproducibilityMetadata.from_config(config)
        assert m1.config_hash == m2.config_hash

    def test_different_config_different_hash(self):
        m1 = ReproducibilityMetadata.from_config({"a": 1})
        m2 = ReproducibilityMetadata.from_config({"a": 2})
        assert m1.config_hash != m2.config_hash

    def test_apply_seed_reproducible(self):
        meta = ReproducibilityMetadata(rng_seed=42, tax_law_version="2024",
                                        code_version="0.2.0", config_hash="abc")
        meta.apply_seed()
        r1 = [random.random() for _ in range(5)]
        meta.apply_seed()
        r2 = [random.random() for _ in range(5)]
        assert r1 == r2

    def test_summary(self):
        meta = ReproducibilityMetadata(rng_seed=42, tax_law_version="2024",
                                        code_version="0.2.0", config_hash="abc123")
        s = meta.summary()
        assert "42" in s
        assert "2024" in s


# ---------------------------------------------------------------------------
# Scenario comparison
# ---------------------------------------------------------------------------
class TestScenarioComparison:

    def test_compare_scenarios(self):
        a = [
            {"year": 2026, "income": 300_000, "taxes": 60_000, "net_worth": 1_000_000},
            {"year": 2027, "income": 310_000, "taxes": 62_000, "net_worth": 1_100_000},
        ]
        b = [
            {"year": 2026, "income": 300_000, "taxes": 55_000, "net_worth": 1_050_000},
            {"year": 2027, "income": 310_000, "taxes": 57_000, "net_worth": 1_200_000},
        ]
        diff = compare_scenarios(a, b, "Baseline", "Roth Convert")
        assert diff.total_tax_savings == pytest.approx(-10_000)  # B pays less tax
        assert diff.final_nw_diff == pytest.approx(100_000)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class TestValidation:

    def test_valid_projection(self):
        projections = [
            {"year": 2026, "income": 300_000, "taxes": 60_000, "net_worth": 1_000_000},
            {"year": 2027, "income": 310_000, "taxes": 62_000, "net_worth": 1_100_000},
        ]
        results = validate_projection(projections)
        assert all(r.passed for r in results)

    def test_negative_net_worth_flagged(self):
        projections = [
            {"year": 2026, "income": 300_000, "taxes": 60_000, "net_worth": -200_000},
        ]
        results = validate_projection(projections)
        errors = [r for r in results if not r.passed and r.severity == "error"]
        assert len(errors) >= 1

    def test_negative_tax_flagged(self):
        projections = [
            {"year": 2026, "income": 300_000, "taxes": -500, "net_worth": 1_000_000},
        ]
        results = validate_projection(projections)
        warnings = [r for r in results if not r.passed and r.severity == "warning"]
        assert len(warnings) >= 1

    def test_empty_projections(self):
        results = validate_projection([])
        assert len(results) >= 1  # Should pass (no data to validate)
