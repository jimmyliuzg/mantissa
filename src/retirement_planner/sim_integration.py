"""
Phase 3: Simulation loop integration — missing wiring.

Provides:
- Dynamic filing status transitions in Monte Carlo
- RSU/concentrated-stock GBM pricing
- Dynamic contribution limits (401k, IRA, HSA + catch-up)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 3a: Dynamic filing status in simulation loop
# ---------------------------------------------------------------------------
def determine_annual_filing_status(
    year: int,
    primary_alive: bool,
    spouse_alive: bool,
    death_year_spouse: Optional[int],
    has_dependents: bool,
) -> str:
    """Determine filing status for a tax year.

    Rules (IRS):
    - Both alive → MFJ
    - Spouse died this year → MFJ (married filing jointly for death year)
    - Years 1-2 after death with dependents → QSS (qualifying surviving spouse)
    - After QSS with dependents → HOH
    - After QSS without dependents → Single
    """
    if primary_alive and spouse_alive:
        return "MFJ"

    if death_year_spouse is None:
        return "MFJ"

    years_since_death = year - death_year_spouse

    # Death year: still MFJ
    if years_since_death == 0:
        return "MFJ"

    # 2 years after death: QSS (if qualifying child/dependent)
    if years_since_death <= 2 and has_dependents:
        return "QSS"

    # After QSS: HOH if dependents, else Single
    if has_dependents:
        return "HOH"

    return "SINGLE"


def compute_survivor_ss_benefit(
    ss_primary_annual: float,
    ss_spouse_annual: float,
    primary_alive: bool,
    spouse_alive: bool,
) -> float:
    """Compute Social Security benefit after spouse death.

    Survivor gets the higher of:
    - Their own benefit
    - 100% of the deceased spouse's benefit
    """
    if primary_alive and spouse_alive:
        return ss_primary_annual + ss_spouse_annual

    if not spouse_alive:
        # Spouse died — primary gets survivor benefit
        return max(ss_primary_annual, ss_spouse_annual)
    else:
        # Primary died — spouse gets survivor benefit
        return max(ss_spouse_annual, ss_primary_annual)


# ---------------------------------------------------------------------------
# 3b: RSU/concentrated-stock GBM pricing
# ---------------------------------------------------------------------------
@dataclass
class GBMParams:
    """Geometric Brownian Motion parameters for a single stock."""
    initial_price: float
    mu: float = 0.08          # expected annual return (nominal)
    sigma: float = 0.35       # annual volatility (typical for single tech stock)
    dividend_yield: float = 0.005
    dt: float = 1.0           # time step in years


def simulate_gbm_path(
    params: GBMParams,
    years: int,
    seed: Optional[int] = None,
) -> List[float]:
    """Simulate a GBM price path for concentrated stock.

    Returns list of prices [price_0, price_1, ..., price_years].
    """
    import random
    import math

    if seed is not None:
        random.seed(seed)

    prices = [params.initial_price]
    price = params.initial_price

    for _ in range(years):
        z = random.gauss(0, 1)
        drift = (params.mu - 0.5 * params.sigma ** 2) * params.dt
        diffusion = params.sigma * math.sqrt(params.dt) * z
        price = price * math.exp(drift + diffusion)
        prices.append(price)

    return prices


def simulate_rsu_value(
    shares_per_year: float,
    stock_prices: List[float],
    sell_fraction: float = 1.0,
) -> List[float]:
    """Compute RSU income each year given a stock price path.

    Args:
        shares_per_year: shares vesting each year
        stock_prices: price path [price_0, price_1, ...]
        sell_fraction: fraction of shares sold at vest (1.0 = sell all)

    Returns: list of dollar values (shares × price × sell_fraction)
    """
    values = []
    for i in range(len(stock_prices)):
        if i == 0:
            values.append(0.0)  # No income at time 0
        else:
            value = shares_per_year * stock_prices[i] * sell_fraction
            values.append(value)
    return values


# ---------------------------------------------------------------------------
# 3c: Dynamic contribution limits
# ---------------------------------------------------------------------------
@dataclass
class ContributionLimits:
    """IRS contribution limits by year, with catch-up provisions."""
    year: int

    # 401(k) / 403(b) / TSP
    elec_deferral_limit: int = 23_500     # 2025
    catch_up_50_plus: int = 7_500         # age 50+
    super_catch_up_60_63: int = 11_250    # SECURE 2.0: ages 60-63

    # Traditional / Roth IRA
    ira_limit: int = 7_000               # 2025
    ira_catch_up_50_plus: int = 1_000

    # HSA (individual / family)
    hsa_individual: int =4_300           # 2025
    hsa_family: int = 8_550
    hsa_catch_up_55_plus: int = 1_000

    # Backdoor Roth (no income limit for conversions, but pro-rata applies)
    roth_ira_income_limit_mfj: int = 240_000  # 2025


# 2024 limits
_LIMITS_2024 = ContributionLimits(
    year=2024,
    elec_deferral_limit=23_000,
    catch_up_50_plus=7_500,
    super_catch_up_60_63=0,  # Not yet in effect
    ira_limit=7_000,
    ira_catch_up_50_plus=1_000,
    hsa_individual=4_150,
    hsa_family=8_300,
    hsa_catch_up_55_plus=1_000,
    roth_ira_income_limit_mfj=230_000,
)

# 2025 limits
_LIMITS_2025 = ContributionLimits(
    year=2025,
    elec_deferral_limit=23_500,
    catch_up_50_plus=7_500,
    super_catch_up_60_63=11_250,
    ira_limit=7_000,
    ira_catch_up_50_plus=1_000,
    hsa_individual=4_300,
    hsa_family=8_550,
    hsa_catch_up_55_plus=1_000,
    roth_ira_income_limit_mfj=240_000,
)

_LIMITS_BY_YEAR = {
    2024: _LIMITS_2024,
    2025: _LIMITS_2025,
}


def get_contribution_limits(year: int, fallback_inflation: float = 0.025) -> ContributionLimits:
    """Get IRS contribution limits for a given year.

    Uses known limits if available, otherwise inflates from nearest year.
    """
    if year in _LIMITS_BY_YEAR:
        return _LIMITS_BY_YEAR[year]

    # Inflate from nearest known year
    base_year = max(y for y in _LIMITS_BY_YEAR if y <= year)
    base = _LIMITS_BY_YEAR[base_year]
    factor = (1 + fallback_inflation) ** (year - base_year)

    return ContributionLimits(
        year=year,
        elec_deferral_limit=int(base.elec_deferral_limit * factor),
        catch_up_50_plus=int(base.catch_up_50_plus * factor),
        super_catch_up_60_63=int(base.super_catch_up_60_63 * factor),
        ira_limit=int(base.ira_limit * factor),
        ira_catch_up_50_plus=int(base.ira_catch_up_50_plus * factor),
        hsa_individual=int(base.hsa_individual * factor),
        hsa_family=int(base.hsa_family * factor),
        hsa_catch_up_55_plus=int(base.hsa_catch_up_55_plus * factor),
        roth_ira_income_limit_mfj=int(base.roth_ira_income_limit_mfj * factor),
    )


def calculate_401k_limit(
    age: int,
    year: int,
    has_employer_plan: bool = True,
) -> int:
    """Calculate max 401(k) contribution for a person."""
    limits = get_contribution_limits(year)

    base = limits.elec_deferral_limit

    # SECURE 2.0 super catch-up for ages 60-63
    if 60 <= age <= 63 and limits.super_catch_up_60_63 > 0:
        base += limits.super_catch_up_60_63
    elif age >= 50:
        base += limits.catch_up_50_plus

    return base


def calculate_ira_limit(
    age: int,
    year: int,
    magi: float,
    filing_status: str = "MFJ",
    has_workplace_plan: bool = False,
) -> int:
    """Calculate deductible IRA contribution limit.

    Phase-out applies if covered by workplace plan.
    """
    limits = get_contribution_limits(year)
    base = limits.ira_limit

    # Catch-up
    if age >= 50:
        base += limits.ira_catch_up_50_plus

    # Phase-out for high earners (simplified)
    if has_workplace_plan:
        if filing_status == "MFJ":
            phase_out_start = 126_000
            phase_out_end = 146_000
        else:
            phase_out_start = 79_000
            phase_out_end = 94_000

        if magi > phase_out_end:
            return 0
        elif magi > phase_out_start:
            fraction = (phase_out_end - magi) / (phase_out_end - phase_out_start)
            return int(base * max(0, fraction))

    return base


def calculate_hsa_limit(
    age: int,
    year: int,
    coverage: str = "family",  # "individual" or "family"
) -> int:
    """Calculate max HSA contribution."""
    limits = get_contribution_limits(year)

    if coverage == "family":
        base = limits.hsa_family
    else:
        base = limits.hsa_individual

    # Catch-up for 55+
    if age >= 55:
        base += limits.hsa_catch_up_55_plus

    return base
