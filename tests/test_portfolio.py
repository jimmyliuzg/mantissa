"""Tests for portfolio.py — capital market model, bond tent, asset location."""
import math
import pytest
from retirement_planner.portfolio import (
    AssetClass, DEFAULT_ASSET_CLASSES, CapitalMarketModel, MarketYear,
    BondTentPolicy, STRESS_SCENARIOS, optimize_asset_location, rebalance_portfolio,
)


# ---------------------------------------------------------------------------
# Asset classes
# ---------------------------------------------------------------------------
class TestAssetClasses:

    def test_default_classes_exist(self):
        assert "us_equity" in DEFAULT_ASSET_CLASSES
        assert "us_bonds" in DEFAULT_ASSET_CLASSES
        assert "tips" in DEFAULT_ASSET_CLASSES
        assert "reits" in DEFAULT_ASSET_CLASSES

    def test_asset_class_fields(self):
        ac = DEFAULT_ASSET_CLASSES["us_equity"]
        assert ac.expected_real_return > 0
        assert ac.volatility > 0
        assert 0 <= ac.income_yield <= 1
        assert 0 <= ac.qualified_div_pct <= 1


# ---------------------------------------------------------------------------
# Capital market model
# ---------------------------------------------------------------------------
class TestCapitalMarketModel:

    def test_sample_year_returns_all_assets(self):
        model = CapitalMarketModel()
        my = model.sample_year(2026)
        assert isinstance(my, MarketYear)
        assert "us_equity" in my.returns
        assert "us_bonds" in my.returns
        assert my.inflation > -0.1  # sanity

    def test_sample_path_length(self):
        model = CapitalMarketModel()
        path = model.sample_path(10, start_year=2026)
        assert len(path) == 10
        assert all(isinstance(p, MarketYear) for p in path)

    def test_nominal_returns_reasonable(self):
        model = CapitalMarketModel()
        # Run 100 samples, check mean is reasonable
        returns = []
        for _ in range(100):
            my = model.sample_year()
            returns.append(my.returns["us_equity"])
        mean_ret = sum(returns) / len(returns)
        # Should be roughly around 7% real + 2.5% inflation ≈ 9.5% nominal
        assert -0.5 < mean_ret < 0.5  # very wide sanity check

    def test_stress_path(self):
        model = CapitalMarketModel()
        path = model.stress_path("dot_com_bear")
        assert len(path) == 3
        # 2000 equity return should be negative
        assert path[0].returns["us_equity"] == pytest.approx(-0.09)

    def test_stress_path_all_scenarios(self):
        model = CapitalMarketModel()
        for sid in STRESS_SCENARIOS:
            path = model.stress_path(sid)
            assert len(path) > 0

    def test_correlation_structure(self):
        """Equity and bond returns should be roughly uncorrelated."""
        model = CapitalMarketModel()
        eq_rets = []
        bond_rets = []
        for _ in range(500):
            my = model.sample_year()
            eq_rets.append(my.returns["us_equity"])
            bond_rets.append(my.returns["us_bonds"])

        # Compute correlation
        n = len(eq_rets)
        mean_eq = sum(eq_rets) / n
        mean_bond = sum(bond_rets) / n
        cov = sum((eq_rets[i] - mean_eq) * (bond_rets[i] - mean_bond) for i in range(n)) / n
        std_eq = math.sqrt(sum((r - mean_eq) ** 2 for r in eq_rets) / n)
        std_bond = math.sqrt(sum((r - mean_bond) ** 2 for r in bond_rets) / n)
        corr = cov / (std_eq * std_bond) if std_eq * std_bond > 0 else 0

        # Should be weakly negative (target: -0.10)
        assert -0.4 < corr < 0.3


# ---------------------------------------------------------------------------
# Bond tent
# ---------------------------------------------------------------------------
class TestBondTent:

    def test_before_tent(self):
        policy = BondTentPolicy(retirement_year=2032)
        # 5+ years before retirement → normal glidepath
        assert policy.equity_weight(2020, 0.80) == 0.80

    def test_during_tent(self):
        policy = BondTentPolicy(retirement_year=2032, minimum_equity_weight=0.30)
        # During tent window → minimum equity
        assert policy.equity_weight(2030, 0.70) == 0.30

    def test_after_tent_recovery(self):
        policy = BondTentPolicy(
            retirement_year=2032,
            minimum_equity_weight=0.30,
            post_tent_target_equity=0.60,
            recovery_years=10,
        )
        # 3 years after tent end → partial recovery
        # tent_end = 2037, year = 2040, elapsed = 3, progress = 0.3
        # weight = 0.30 + 0.3 * (0.60 - 0.30) = 0.39
        weight = policy.equity_weight(2040, 0.65)
        assert 0.35 < weight < 0.45

    def test_after_full_recovery(self):
        policy = BondTentPolicy(
            retirement_year=2032,
            post_tent_target_equity=0.60,
            recovery_years=10,
        )
        # 15+ years after tent end → post-tent target
        assert policy.equity_weight(2055, 0.65) == 0.60


# ---------------------------------------------------------------------------
# Asset location
# ---------------------------------------------------------------------------
class TestAssetLocation:

    def test_bonds_in_tax_deferred(self):
        accounts = {
            "401k": {"type": "401k", "balance": 500_000, "tax_treatment": "pre_tax"},
            "brokerage": {"type": "brokerage", "balance": 300_000, "tax_treatment": "taxable"},
        }
        target = {"us_equity": 0.6, "us_bonds": 0.4}
        result = optimize_asset_location(accounts, target, DEFAULT_ASSET_CLASSES)
        # Bonds should be preferentially in 401k
        assert result["401k"].get("us_bonds", 0) > 0

    def test_equity_in_taxable(self):
        accounts = {
            "401k": {"type": "401k", "balance": 500_000, "tax_treatment": "pre_tax"},
            "brokerage": {"type": "brokerage", "balance": 300_000, "tax_treatment": "taxable"},
        }
        target = {"us_equity": 0.6, "us_bonds": 0.4}
        result = optimize_asset_location(accounts, target, DEFAULT_ASSET_CLASSES)
        # Some equity should be in taxable
        assert result["brokerage"].get("us_equity", 0) > 0


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------
class TestRebalancing:

    def test_no_trade_when_within_band(self):
        current = {"us_equity": 0.62, "us_bonds": 0.38}
        target = {"us_equity": 0.60, "us_bonds": 0.40}
        result = rebalance_portfolio(current, target, 1_000_000, {}, band=0.05)
        assert len(result.trades) == 0

    def test_trade_when_outside_band(self):
        current = {"us_equity": 0.70, "us_bonds": 0.30}
        target = {"us_equity": 0.60, "us_bonds": 0.40}
        result = rebalance_portfolio(current, target, 1_000_000, {}, band=0.05)
        assert len(result.trades) > 0

    def test_deviation_reduced(self):
        current = {"us_equity": 0.75, "us_bonds": 0.25}
        target = {"us_equity": 0.60, "us_bonds": 0.40}
        result = rebalance_portfolio(current, target, 1_000_000, {}, band=0.01)
        assert result.deviation_before > 0.10
        assert result.deviation_after == 0.0

    def test_tax_cost_on_gain(self):
        current = {"us_equity": 0.80, "us_bonds": 0.20}
        target = {"us_equity": 0.60, "us_bonds": 0.40}
        cost_basis = {"us_equity": 100_000}  # $100K basis on $800K equity
        result = rebalance_portfolio(
            current, target, 1_000_000, cost_basis, tax_rate=0.15, band=0.01,
        )
        # Selling $200K equity with $100K basis → $100K gain → $15K tax
        assert result.total_tax_cost > 0
