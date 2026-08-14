"""Sweep round 4: historical conventions, sensitivity restore, PDF None growth."""
from datetime import date

import numpy as np
import pytest

from retirement_planner import RetirementPlanner
from retirement_planner.historical_data import _HISTORICAL_SNP500_VALUES
from retirement_planner.models import (
    Account, EconomicAssumptions, MonetaryConvention, Person, Scenario,
)
from retirement_planner.sensitivity import SensitivityAnalyzer


def _hist_planner(convention):
    scenario = Scenario(
        name="h", description="",
        primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
        spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
        economic=EconomicAssumptions(),
        accounts=[Account("b", "B", "brokerage", "taxable", 100_000,
                          growth_rate=0.07)],
        income_streams=[], expenses=[], mortgages=[],
        monetary_convention=convention,
    )
    return RetirementPlanner(scenario)


class TestHistoricalConvention:
    """The historical series is NOMINAL total returns; the engine must
    convert per convention exactly once."""

    def test_series_is_nominal(self):
        # 2021 S&P 500 total return was +28.7% NOMINAL (real ~+23%)
        assert _HISTORICAL_SNP500_VALUES[-3] == pytest.approx(0.287)

    def test_real_mode_deflates(self):
        p = _hist_planner(MonetaryConvention.REAL)
        p._historical_return_override = _HISTORICAL_SNP500_VALUES
        run = p.run_single_simulation(return_volatility=0.0)
        prod = 1.0
        for r in _HISTORICAL_SNP500_VALUES[:52]:
            prod *= (1.0 + r) / 1.0254
        assert run["final_net_worth"] == pytest.approx(100_000 * prod, rel=1e-9)

    def test_nominal_mode_uses_raw(self):
        p = _hist_planner(MonetaryConvention.NOMINAL)
        p._historical_return_override = _HISTORICAL_SNP500_VALUES
        run = p.run_single_simulation(return_volatility=0.0)
        prod = 1.0
        for r in _HISTORICAL_SNP500_VALUES[:52]:
            prod *= 1.0 + r
        assert run["final_net_worth"] == pytest.approx(100_000 * prod, rel=1e-9)


class TestSensitivityRestore:
    def test_per_account_rates_restored(self):
        scenario = Scenario(
            name="s", description="",
            primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
            spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
            economic=EconomicAssumptions(),
            accounts=[
                Account("a", "A", "brokerage", "taxable", 100_000,
                        growth_rate=0.07),
                Account("c", "C", "checking", "taxable", 10_000,
                        growth_rate=0.04),
                Account("e", "E", "brokerage", "taxable", 50_000),  # CMA None
            ],
            income_streams=[], expenses=[], mortgages=[],
        )
        planner = RetirementPlanner(scenario)
        analyzer = SensitivityAnalyzer(planner)
        results = analyzer.run(
            "investment_return_mean", [0.05, 0.06], num_simulations=2)
        assert len(results) == 2
        # Restored exactly: per-account rates survive, including None
        assert planner.accounts["a"].growth_rate == 0.07
        assert planner.accounts["c"].growth_rate == 0.04
        assert planner.accounts["e"].growth_rate is None

    def test_exception_still_restores(self):
        scenario = Scenario(
            name="s", description="",
            primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
            spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
            economic=EconomicAssumptions(),
            accounts=[Account("a", "A", "brokerage", "taxable", 100_000,
                              growth_rate=0.07)],
            income_streams=[], expenses=[], mortgages=[],
        )
        planner = RetirementPlanner(scenario)
        analyzer = SensitivityAnalyzer(planner)
        with pytest.raises(ValueError):
            analyzer.run("nonsense", [0.05], num_simulations=2)
        assert planner.accounts["a"].growth_rate == 0.07


class TestPdfReportNoneGrowth:
    def test_assumptions_handles_cma_accounts(self):
        reportlab = pytest.importorskip("reportlab")
        from retirement_planner.pdf_report import _section_assumptions
        from retirement_planner.models import Person, Scenario

        scenario = Scenario(
            name="p", description="",
            primary=Person("P", date(1980, 1, 1), date(2026, 1, 1), 95),
            spouse=Person("S", date(1982, 1, 1), date(2026, 1, 1), 95),
            economic=EconomicAssumptions(),
            accounts=[
                Account("a", "A", "brokerage", "taxable", 100_000),  # None
                Account("re", "RE", "real_estate", "taxable", 500_000,
                        liquid=False),  # None
            ],
            income_streams=[], expenses=[], mortgages=[],
        )
        styles = {
            "SectionHead": reportlab.lib.styles.ParagraphStyle("SectionHead"),
            "SubHead": reportlab.lib.styles.ParagraphStyle("SubHead"),
            "Body": reportlab.lib.styles.ParagraphStyle("Body"),
        }
        elements = _section_assumptions(styles, scenario)
        assert elements  # does not raise on growth_rate=None
