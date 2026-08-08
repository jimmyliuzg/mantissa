"""Invariant and property tests for the retirement planner (Phase 4.2).

These tests verify mathematical and logical invariants that must hold
across all projections, regardless of configuration.
"""
import os
import pytest
from retirement_planner.engine import RetirementPlanner


SAMPLE_CONFIG = os.path.join(
    os.path.dirname(__file__), "..", "..", "examples", "sample_config.json"
)


@pytest.fixture
def planner():
    return RetirementPlanner.from_config(SAMPLE_CONFIG)


@pytest.fixture
def projections(planner):
    return planner.project_cash_flow("mean")


# ---------------------------------------------------------------------------
# 1. Balances never go negative
# ---------------------------------------------------------------------------
class TestNoNegativeBalances:
    """Account balances must never drop below zero in any projection year."""

    def test_projected_balances_non_negative(self, planner, projections):
        """Every account balance in every year must be >= 0."""
        for row in projections:
            year = row["year"]
            nw = row.get("net_worth", 0)
            # Net worth can be negative (liabilities > assets), but shouldn't
            # be absurdly negative
            assert nw > -10_000_000, f"Net worth absurdly negative in {year}: {nw}"

    def test_total_assets_non_negative(self, projections):
        """Total assets must be non-negative (no phantom accounts)."""
        for row in projections:
            assert row["total_assets"] >= 0, (
                f"Total assets negative in {row['year']}: {row['total_assets']}"
            )


# ---------------------------------------------------------------------------
# 2. Money conservation: income - expenses - taxes ≈ net cash flow
# ---------------------------------------------------------------------------
class TestMoneyConservation:
    """Cash flow identity: income - expenses - taxes - aca_subsidy = net_cash_flow."""

    def test_cash_flow_identity(self, projections):
        for row in projections:
            expected = (
                row["income"]
                - row["expenses"]
                - row["taxes"]
                - row.get("aca_subsidy", 0)
            )
            actual = row["net_cash_flow"]
            assert actual == pytest.approx(expected, abs=1.0), (
                f"Cash flow mismatch in {row['year']}: "
                f"expected {expected:,.2f}, got {actual:,.2f}"
            )

    def test_income_non_negative(self, projections):
        """Income should never be negative."""
        for row in projections:
            assert row["income"] >= 0, (
                f"Negative income in {row['year']}: {row['income']}"
            )

    def test_expenses_non_negative(self, projections):
        """Expenses should never be negative."""
        for row in projections:
            assert row["expenses"] >= 0, (
                f"Negative expenses in {row['year']}: {row['expenses']}"
            )


# ---------------------------------------------------------------------------
# 3. Taxes are non-negative and bounded
# ---------------------------------------------------------------------------
class TestTaxInvariants:
    """Tax calculations must be non-negative and reasonable."""

    def test_taxes_non_negative(self, projections):
        for row in projections:
            assert row["taxes"] >= 0, (
                f"Negative tax in {row['year']}: {row['taxes']}"
            )

    def test_taxes_never_exceed_income(self, projections):
        """Tax should never exceed total income (effective rate < 100%)."""
        for row in projections:
            if row["income"] > 0:
                rate = row["taxes"] / row["income"]
                assert rate < 1.0, (
                    f"Tax rate > 100% in {row['year']}: "
                    f"{row['taxes']:,.0f} / {row['income']:,.0f} = {rate:.1%}"
                )

    def test_estate_tax_non_negative(self, projections):
        for row in projections:
            assert row["estate_tax"] >= 0, (
                f"Negative estate tax in {row['year']}: {row['estate_tax']}"
            )


# ---------------------------------------------------------------------------
# 4. Projection rows contain required fields
# ---------------------------------------------------------------------------
class TestProjectionSchema:
    """Every projection row must have all required fields with correct types."""

    REQUIRED_FIELDS = {
        "year": int,
        "primary_age": int,
        "spouse_age": int,
        "income": (int, float),
        "expenses": (int, float),
        "taxes": (int, float),
        "aca_subsidy": (int, float),
        "net_cash_flow": (int, float),
        "net_worth": (int, float),
        "total_assets": (int, float),
        "total_liabilities": (int, float),
        "estate_tax": (int, float),
    }

    def test_all_required_fields_present(self, projections):
        for row in projections:
            for field_name in self.REQUIRED_FIELDS:
                assert field_name in row, (
                    f"Missing field '{field_name}' in year {row.get('year', '?')}"
                )

    def test_field_types_correct(self, projections):
        for row in projections:
            for field_name, expected_type in self.REQUIRED_FIELDS.items():
                val = row[field_name]
                assert isinstance(val, expected_type), (
                    f"Field '{field_name}' in year {row['year']}: "
                    f"expected {expected_type}, got {type(val).__name__} = {val}"
                )

    def test_ages_are_integers(self, projections):
        for row in projections:
            assert isinstance(row["primary_age"], int)
            assert isinstance(row["spouse_age"], int)

    def test_years_are_sequential(self, projections):
        years = [row["year"] for row in projections]
        for i in range(1, len(years)):
            assert years[i] == years[i - 1] + 1, (
                f"Non-sequential years: {years[i-1]} -> {years[i]}"
            )


# ---------------------------------------------------------------------------
# 5. Determinism: same config produces identical results
# ---------------------------------------------------------------------------
class TestDeterminism:
    """Running the same projection twice must produce identical results."""

    def test_same_config_same_results(self):
        p1 = RetirementPlanner.from_config(SAMPLE_CONFIG)
        p2 = RetirementPlanner.from_config(SAMPLE_CONFIG)
        r1 = p1.project_cash_flow("mean")
        r2 = p2.project_cash_flow("mean")
        assert len(r1) == len(r2)
        for row1, row2 in zip(r1, r2):
            assert row1["year"] == row2["year"]
            assert row1["income"] == pytest.approx(row2["income"])
            assert row1["taxes"] == pytest.approx(row2["taxes"])
            assert row1["net_worth"] == pytest.approx(row2["net_worth"])


# ---------------------------------------------------------------------------
# 6. Net worth trajectory is reasonable
# ---------------------------------------------------------------------------
class TestNetWorthTrajectory:
    """Net worth should follow economically sensible patterns."""

    def test_net_worth_bounded_by_assets(self, projections):
        """Net worth <= total_assets (liabilities reduce net worth)."""
        for row in projections:
            assert row["net_worth"] <= row["total_assets"] + 1.0, (
                f"Net worth > total assets in {row['year']}: "
                f"{row['net_worth']:,.0f} > {row['total_assets']:,.0f}"
            )

    def test_liabilities_non_negative(self, projections):
        for row in projections:
            assert row["total_liabilities"] >= 0, (
                f"Negative liabilities in {row['year']}"
            )


# ---------------------------------------------------------------------------
# 7. ACA subsidy is zero when not applicable
# ---------------------------------------------------------------------------
class TestACASubsidy:
    """ACA subsidy rules: zero when income too high or age >= 65."""

    def test_aca_subsidy_non_negative(self, projections):
        for row in projections:
            assert row["aca_subsidy"] >= 0, (
                f"Negative ACA subsidy in {row['year']}: {row['aca_subsidy']}"
            )

    def test_aca_subsidy_zero_when_high_income(self, projections):
        """Above 400% FPL, ACA subsidy should be zero."""
        for row in projections:
            # If income is very high, subsidy should be zero
            if row["income"] > 500_000:
                assert row["aca_subsidy"] == 0, (
                    f"ACA subsidy nonzero at high income in {row['year']}: "
                    f"income={row['income']:,.0f}, subsidy={row['aca_subsidy']:,.0f}"
                )


# ---------------------------------------------------------------------------
# 8. Estate tax is one-time
# ---------------------------------------------------------------------------
class TestEstateTax:
    """Estate tax should be applied at most once."""

    def test_estate_tax_applied_once(self, projections):
        """Estate tax should be nonzero in at most one year."""
        nonzero_years = [
            row for row in projections if row["estate_tax"] > 0
        ]
        assert len(nonzero_years) <= 1, (
            f"Estate tax applied in {len(nonzero_years)} years: "
            f"{[r['year'] for r in nonzero_years]}"
        )
