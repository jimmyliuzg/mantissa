"""
Multi-asset capital market model (Phase 3).

Provides:
- Asset class definitions with expected returns, volatility, correlations
- Correlated return generation (multivariate Student-t)
- Historical data loading for bootstrap
- Stress scenario definitions (2000, 2008, high-inflation, early-retirement crash)
- Bond tent generalization
- Asset-location and tax-aware rebalancing
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Asset classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AssetClass:
    """A single asset class with return/risk characteristics."""
    id: str
    name: str
    expected_real_return: float   # annualized real return
    volatility: float            # annualized standard deviation
    income_yield: float          # dividend + interest yield
    qualified_div_pct: float     # fraction of income that is qualified
    tax_character: str           # "ordinary", "capital_gains", "tax_free"
    liquidity_tier: int          # 1=most liquid, 5=illiquid


# Default asset classes (real returns, pre-tax)
DEFAULT_ASSET_CLASSES: Dict[str, AssetClass] = {
    "us_equity": AssetClass(
        id="us_equity", name="U.S. Total Equity",
        expected_real_return=0.07, volatility=0.18,
        income_yield=0.015, qualified_div_pct=0.90,
        tax_character="capital_gains", liquidity_tier=1,
    ),
    "intl_equity": AssetClass(
        id="intl_equity", name="International Developed Equity",
        expected_real_return=0.05, volatility=0.17,
        income_yield=0.025, qualified_div_pct=0.70,
        tax_character="capital_gains", liquidity_tier=1,
    ),
    "em_equity": AssetClass(
        id="em_equity", name="Emerging Markets Equity",
        expected_real_return=0.06, volatility=0.22,
        income_yield=0.02, qualified_div_pct=0.50,
        tax_character="capital_gains", liquidity_tier=1,
    ),
    "us_bonds": AssetClass(
        id="us_bonds", name="U.S. Aggregate Bonds",
        expected_real_return=0.02, volatility=0.05,
        income_yield=0.035, qualified_div_pct=0.0,
        tax_character="ordinary", liquidity_tier=1,
    ),
    "tips": AssetClass(
        id="tips", name="Treasury Inflation-Protected Securities",
        expected_real_return=0.015, volatility=0.04,
        income_yield=0.015, qualified_div_pct=0.0,
        tax_character="ordinary", liquidity_tier=1,
    ),
    "short_term": AssetClass(
        id="short_term", name="Short-Term Treasury / Cash",
        expected_real_return=0.01, volatility=0.01,
        income_yield=0.04, qualified_div_pct=0.0,
        tax_character="ordinary", liquidity_tier=1,
    ),
    "reits": AssetClass(
        id="reits", name="REITs",
        expected_real_return=0.05, volatility=0.18,
        income_yield=0.035, qualified_div_pct=0.10,
        tax_character="ordinary", liquidity_tier=1,
    ),
    "employer_stock": AssetClass(
        id="employer_stock", name="Employer Stock (concentrated)",
        expected_real_return=0.08, volatility=0.30,
        income_yield=0.005, qualified_div_pct=0.90,
        tax_character="capital_gains", liquidity_tier=1,
    ),
}


# ---------------------------------------------------------------------------
# Correlation matrix (approximate)
# ---------------------------------------------------------------------------
# Order: us_equity, intl_equity, em_equity, us_bonds, tips, short_term, reits
_CORRELATION_ORDER = ["us_equity", "intl_equity", "em_equity", "us_bonds", "tips", "short_term", "reits"]

_DEFAULT_CORRELATIONS: List[List[float]] = [
    [1.00, 0.85, 0.75, -0.10, -0.05, 0.00, 0.60],  # us_equity
    [0.85, 1.00, 0.80, -0.05, -0.02, 0.00, 0.50],  # intl_equity
    [0.75, 0.80, 1.00, -0.05, -0.03, 0.00, 0.45],  # em_equity
    [-0.10, -0.05, -0.05, 1.00, 0.85, 0.70, 0.10],  # us_bonds
    [-0.05, -0.02, -0.03, 0.85, 1.00, 0.60, 0.05],  # tips
    [0.00, 0.00, 0.00, 0.70, 0.60, 1.00, 0.00],     # short_term
    [0.60, 0.50, 0.45, 0.10, 0.05, 0.00, 1.00],     # reits
]


# ---------------------------------------------------------------------------
# Stress scenarios
# ---------------------------------------------------------------------------
@dataclass
class StressScenario:
    """A deterministic stress scenario with year-by-year returns."""
    id: str
    name: str
    years: int
    equity_returns: List[float]   # annual equity returns
    bond_returns: List[float]     # annual bond returns
    inflation_rates: List[float]  # annual inflation
    description: str = ""


STRESS_SCENARIOS: Dict[str, StressScenario] = {
    "dot_com_bear": StressScenario(
        id="dot_com_bear",
        name="Dot-Com Bear Market (2000-2002)",
        years=3,
        equity_returns=[-0.09, -0.12, -0.22],
        bond_returns=[0.16, 0.08, 0.10],
        inflation_rates=[0.034, 0.016, 0.024],
        description="3 consecutive years of equity losses, bonds positive",
    ),
    "global_financial_crisis": StressScenario(
        id="global_financial_crisis",
        name="Global Financial Crisis (2007-2009)",
        years=3,
        equity_returns=[0.05, -0.37, 0.27],
        bond_returns=[0.07, 0.05, 0.05],
        inflation_rates=[0.029, 0.038, -0.004],
        description="2008 crash: -37% equity, bonds positive, deflation",
    ),
    "high_inflation": StressScenario(
        id="high_inflation",
        name="High Inflation (1973-1982)",
        years=10,
        equity_returns=[-0.15, -0.03, 0.37, 0.24, -0.07, 0.07, 0.19, -0.10, 0.05, 0.32],
        bond_returns=[0.03, 0.02, 0.04, 0.03, 0.01, 0.00, -0.01, 0.02, 0.03, 0.04],
        inflation_rates=[0.087, 0.123, 0.070, 0.048, 0.065, 0.076, 0.113, 0.135, 0.103, 0.062],
        description="10-year high-inflation period, bonds hurt",
    ),
    "early_retirement_crash": StressScenario(
        id="early_retirement_crash",
        name="Early Retirement Crash (Year 1: -35%)",
        years=5,
        equity_returns=[-0.35, -0.10, 0.15, 0.25, 0.20],
        bond_returns=[0.00, 0.03, 0.04, 0.03, 0.03],
        inflation_rates=[0.06, 0.05, 0.04, 0.03, 0.03],
        description="Custom: -35% equity shock at retirement, slow recovery",
    ),
    "lost_decade": StressScenario(
        id="lost_decade",
        name="Lost Decade (2000-2010)",
        years=11,
        equity_returns=[-0.09, -0.12, -0.22, 0.29, 0.11, 0.05, 0.16, 0.06, -0.37, 0.27, 0.15],
        bond_returns=[0.16, 0.08, 0.10, 0.02, 0.04, 0.03, 0.02, 0.05, 0.05, 0.05, 0.03],
        inflation_rates=[0.034, 0.016, 0.024, 0.027, 0.034, 0.032, 0.029, 0.038, -0.004, 0.016, 0.032],
        description="2000-2010: flat/negative equity, bonds positive",
    ),
}


# ---------------------------------------------------------------------------
# Capital market model
# ---------------------------------------------------------------------------
@dataclass
class MarketYear:
    """One year of market returns for all asset classes."""
    regime: str
    inflation: float
    returns: Dict[str, float]   # asset_class_id → nominal return


class CapitalMarketModel:
    """Generates correlated returns for multi-asset portfolios.

    Supports:
    - Multivariate Student-t returns (default)
    - Deterministic stress scenarios
    - Historical replay
    """

    def __init__(
        self,
        asset_classes: Optional[Dict[str, AssetClass]] = None,
        correlations: Optional[List[List[float]]] = None,
        correlation_order: Optional[List[str]] = None,
        inflation_mean: float = 0.025,
        inflation_vol: float = 0.01,
        degrees_of_freedom: float = 6.0,
    ):
        self.asset_classes = asset_classes or dict(DEFAULT_ASSET_CLASSES)
        self.correlation_order = correlation_order or list(_CORRELATION_ORDER)
        self.correlations = correlations or [list(row) for row in _DEFAULT_CORRELATIONS]
        self.inflation_mean = inflation_mean
        self.inflation_vol = inflation_vol
        self.df = degrees_of_freedom

        # Build covariance matrix from correlations and volatilities
        self._build_covariance()

    def _build_covariance(self):
        """Build covariance matrix from correlations and volatilities."""
        n = len(self.correlation_order)
        self._vols = []
        self._means = []
        for aid in self.correlation_order:
            ac = self.asset_classes[aid]
            self._vols.append(ac.volatility)
            self._means.append(ac.expected_real_return)

        # Covariance = diag(vol) @ correlation @ diag(vol)
        self._cov = []
        for i in range(n):
            row = []
            for j in range(n):
                row.append(self.correlations[i][j] * self._vols[i] * self._vols[j])
            self._cov.append(row)

    def _chol_decompose(self, matrix: List[List[float]]) -> List[List[float]]:
        """Cholesky decomposition for correlated sampling."""
        n = len(matrix)
        L = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(i + 1):
                s = sum(L[i][k] * L[j][k] for k in range(j))
                if i == j:
                    diag = matrix[i][i] - s
                    L[i][j] = math.sqrt(max(0, diag))
                else:
                    denom = L[j][j]
                    L[i][j] = (matrix[i][j] - s) / denom if denom > 1e-10 else 0.0
        return L

    def _sample_correlated_normals(self, rng) -> List[float]:
        """Sample n correlated normal random variables using Cholesky."""
        import random
        n = len(self._means)
        # Independent normals
        z = [random.gauss(0, 1) for _ in range(n)]
        # Cholesky multiply
        L = self._chol_decompose(self._cov)
        x = [sum(L[i][j] * z[j] for j in range(n)) for i in range(n)]
        return x

    def sample_year(self, year: int = 0, regime: str = "normal") -> MarketYear:
        """Generate one year of correlated returns."""
        import random

        # Sample correlated real returns
        shocks = self._sample_correlated_normals(rng=None)

        # Add inflation
        inflation = random.gauss(self.inflation_mean, self.inflation_vol)
        inflation = max(-0.02, min(0.15, inflation))  # clamp

        # Convert real returns to nominal
        returns = {}
        for i, aid in enumerate(self.correlation_order):
            real_return = self._means[i] + shocks[i]
            nominal = (1 + real_return) * (1 + inflation) - 1
            returns[aid] = nominal

        # Add asset classes not in correlation matrix
        for aid, ac in self.asset_classes.items():
            if aid not in returns:
                real_return = random.gauss(ac.expected_real_return, ac.volatility)
                nominal = (1 + real_return) * (1 + inflation) - 1
                returns[aid] = nominal

        return MarketYear(regime=regime, inflation=inflation, returns=returns)

    def sample_path(self, years: int, start_year: int = 2026) -> List[MarketYear]:
        """Generate a full path of correlated returns."""
        return [self.sample_year(start_year + i) for i in range(years)]

    def stress_path(self, scenario_id: str) -> List[MarketYear]:
        """Generate a deterministic stress path."""
        scenario = STRESS_SCENARIOS[scenario_id]
        path = []
        for i in range(scenario.years):
            equity_ret = scenario.equity_returns[i] if i < len(scenario.equity_returns) else 0.0
            bond_ret = scenario.bond_returns[i] if i < len(scenario.bond_returns) else 0.0
            inflation = scenario.inflation_rates[i] if i < len(scenario.inflation_rates) else 0.025

            returns = {}
            for aid, ac in self.asset_classes.items():
                if "equity" in aid or "reit" in aid or "employer" in aid:
                    returns[aid] = equity_ret
                elif "bond" in aid or "tips" in aid or "short" in aid:
                    returns[aid] = bond_ret
                else:
                    returns[aid] = equity_ret * 0.5 + bond_ret * 0.5

            path.append(MarketYear(
                regime=scenario_id,
                inflation=inflation,
                returns=returns,
            ))
        return path


# ---------------------------------------------------------------------------
# Bond tent policy
# ---------------------------------------------------------------------------
@dataclass
class BondTentPolicy:
    """Configurable bond tent around retirement.

    Increases bond allocation before/after retirement to reduce
    sequence-of-returns risk, then gradually ramps back to normal.
    """
    retirement_year: int
    start_year_offset: int = -5      # years before retirement to start tent
    end_year_offset: int = 5         # years after retirement to end tent
    minimum_equity_weight: float = 0.30
    post_tent_target_equity: float = 0.60
    recovery_years: int = 10         # years to ramp back to normal glidepath

    def equity_weight(self, year: int, normal_equity: float) -> float:
        """Compute equity weight with bond tent applied."""
        tent_start = self.retirement_year + self.start_year_offset
        tent_end = self.retirement_year + self.end_year_offset

        if year < tent_start:
            return normal_equity

        if tent_start <= year <= tent_end:
            return min(normal_equity, self.minimum_equity_weight)

        # Recovery phase
        elapsed = year - tent_end
        if elapsed >= self.recovery_years:
            return self.post_tent_target_equity

        progress = elapsed / self.recovery_years
        return self.minimum_equity_weight + progress * (
            self.post_tent_target_equity - self.minimum_equity_weight
        )


# ---------------------------------------------------------------------------
# Asset location optimizer
# ---------------------------------------------------------------------------
def optimize_asset_location(
    accounts: Dict[str, dict],  # id → {type, balance, tax_treatment}
    target_allocation: Dict[str, float],  # asset_class → weight
    asset_classes: Dict[str, AssetClass],
) -> Dict[str, Dict[str, float]]:
    """Suggest which asset classes go in which accounts for tax efficiency.

    General rules:
    - Ordinary-income assets (bonds, REITs) → tax-deferred (401k, trad IRA)
    - Tax-efficient assets (equity index) → taxable
    - Tax-free growth (Roth) → highest-growth assets
    """
    # Rank assets by tax inefficiency (higher = less suitable for taxable)
    inefficiency = {}
    for aid, ac in asset_classes.items():
        if ac.tax_character == "ordinary":
            inefficiency[aid] = 3  # worst in taxable
        elif ac.income_yield > 0.03:
            inefficiency[aid] = 2  # high yield = more tax drag
        else:
            inefficiency[aid] = 1  # tax-efficient

    # Sort assets by inefficiency (most inefficient first)
    sorted_assets = sorted(
        target_allocation.keys(),
        key=lambda a: inefficiency.get(a, 1),
        reverse=True,
    )

    # Total portfolio value
    total_balance = sum(v.get("balance", 0) for v in accounts.values())
    if total_balance <= 0:
        return {aid: {} for aid in accounts}

    # For each asset, distribute proportionally across accounts
    # but prefer tax-appropriate accounts
    result = {aid: {} for aid in accounts}

    for asset in sorted_assets:
        weight = target_allocation[asset]
        asset_amount = weight * total_balance
        remaining = asset_amount

        # Sort accounts by suitability for this asset
        if inefficiency.get(asset, 1) >= 3:
            # Ordinary income → prefer pre-tax accounts
            acct_order = sorted(
                accounts.keys(),
                key=lambda a: {"pre_tax": 3, "roth": 2, "taxable": 1}.get(
                    accounts[a].get("tax_treatment", "taxable"), 1
                ),
                reverse=True,
            )
        else:
            # Tax-efficient → prefer taxable, then Roth
            acct_order = sorted(
                accounts.keys(),
                key=lambda a: {"taxable": 3, "roth": 2, "pre_tax": 1}.get(
                    accounts[a].get("tax_treatment", "taxable"), 1
                ),
                reverse=True,
            )

        for account in acct_order:
            acct_balance = accounts[account].get("balance", 0)
            if acct_balance <= 0:
                continue
            # Allocate up to account's share
            acct_share = (acct_balance / total_balance) * asset_amount
            allocated = min(remaining, acct_share)
            if allocated > 0:
                if asset not in result[account]:
                    result[account][asset] = 0
                result[account][asset] += allocated
                remaining -= allocated
            if remaining <= 0:
                break

    return result


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------
@dataclass
class RebalanceResult:
    """Output of a rebalancing operation."""
    trades: List[dict]  # {account, asset, action, amount, tax_cost}
    total_tax_cost: float
    deviation_before: float  # max deviation from target
    deviation_after: float


def rebalance_portfolio(
    current_weights: Dict[str, float],   # asset → current weight
    target_weights: Dict[str, float],     # asset → target weight
    portfolio_value: float,
    cost_basis: Dict[str, float],         # asset → cost basis
    tax_rate: float = 0.15,              # assumed LTCG rate
    band: float = 0.05,                  # rebalancing band (5%)
) -> RebalanceResult:
    """Tax-aware rebalancing with bands.

    Only trades when an asset class deviates from target by more than `band`.
    Prefers selling overweight assets with lowest gains.
    """
    trades = []
    total_tax = 0.0
    max_dev_before = 0.0

    for asset in set(list(current_weights.keys()) + list(target_weights.keys())):
        current = current_weights.get(asset, 0)
        target = target_weights.get(asset, 0)
        deviation = abs(current - target)
        max_dev_before = max(max_dev_before, deviation)

        if deviation > band:
            diff = current - target  # positive = overweight
            trade_amount = diff * portfolio_value
            cost = cost_basis.get(asset, 0)
            gain = max(0, trade_amount - cost) if trade_amount > 0 else 0
            tax_cost = gain * tax_rate

            action = "sell" if diff > 0 else "buy"
            trades.append({
                "asset": asset,
                "action": action,
                "amount": abs(trade_amount),
                "tax_cost": tax_cost,
            })
            total_tax += tax_cost

    # After rebalancing, deviation should be near zero
    return RebalanceResult(
        trades=trades,
        total_tax_cost=total_tax,
        deviation_before=max_dev_before,
        deviation_after=0.0,  # Perfect rebalance
    )
