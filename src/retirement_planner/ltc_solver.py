"""
Phase 5: Long-term care events and reverse solver.

LTC Events:
- Stochastic shock: probability × duration × annual cost
- Triggered per simulation path, draws down portfolio
- Configurable: probability, duration, annual cost, age range

Reverse Solver:
- Binary search over a lever (savings rate, retirement age, spending)
- Uses Monte Carlo as evaluation function
- Target: specific success rate (e.g., 90%)
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Long-term care events
# ---------------------------------------------------------------------------
@dataclass
class LTCConfig:
    """Configuration for stochastic long-term care events."""
    # Probability of needing LTC in any given year (age-dependent)
    base_probability: float = 0.02      # 2% per year base
    # Duration of LTC event (in years)
    min_duration: int = 1
    max_duration: int = 5
    mean_duration: float = 2.5
    # Annual cost of LTC
    annual_cost: float = 100_000        # $100K/year (nursing home)
    # Age range where LTC is possible
    start_age: int = 75
    end_age: int = 100
    # Inflation for LTC costs (distinct from general inflation)
    ltc_inflation: float = 0.05         # 5% annual growth in LTC costs
    # Copay: fraction of cost paid by individual (rest by insurance)
    copay_pct: float = 1.0             # 100% without insurance
    # Asset protection: ignore first N dollars
    asset_shield: float = 0.0          # e.g., $500K protected


@dataclass
class LTCEvent:
    """A long-term care event that occurred."""
    start_age: int
    duration_years: int
    annual_cost: float
    total_cost: float
    age_at_onset: int
    portfolio_impact: float  # actual amount drawn from portfolio


def simulate_ltc_events(
    config: LTCConfig,
    current_age: int,
    max_age: int = 105,
    portfolio_value: float = 0.0,
    seed: Optional[int] = None,
) -> List[LTCEvent]:
    """Simulate stochastic LTC events for one life path.

    Returns list of LTC events (can be 0, 1, or rarely multiple).
    """
    if seed is not None:
        random.seed(seed)

    events = []
    age = current_age

    while age < max_age:
        if config.start_age <= age <= config.end_age:
            # Check if LTC event occurs this year
            if random.random() < config.base_probability:
                # Determine duration
                duration = max(config.min_duration,
                             min(config.max_duration,
                                 int(random.gauss(config.mean_duration, 1.0))))

                # Calculate cost (with inflation)
                years_from_now = age - current_age
                inflated_cost = config.annual_cost * (
                    (1 + config.ltc_inflation) ** years_from_now
                )
                total = inflated_cost * duration * config.copay_pct

                # Apply asset shield: protects first N of portfolio
                # LTC cost can only draw from unprotected assets
                if config.asset_shield > 0:
                    protected = min(config.asset_shield, portfolio_value)
                    unprotected = max(0, portfolio_value - protected)
                    total = min(total, unprotected)  # can't exceed unprotected

                event = LTCEvent(
                    start_age=age,
                    duration_years=duration,
                    annual_cost=inflated_cost,
                    total_cost=total,
                    age_at_onset=age,
                    portfolio_impact=total,
                )
                events.append(event)

                # Skip ahead past the LTC event
                age += duration
                continue

        age += 1

    return events


def calculate_ltc_annual_cost(
    age: int,
    config: LTCConfig,
    years_from_start: int = 0,
) -> float:
    """Calculate annual LTC cost for a given age (with inflation)."""
    if age < config.start_age or age > config.end_age:
        return 0.0
    return config.annual_cost * ((1 + config.ltc_inflation) ** years_from_start)


def ltc_probability_by_age(age: int, config: LTCConfig) -> float:
    """Return probability of needing LTC at a given age.

    Uses a simplified age-dependent model:
    - Below start_age: 0
    - At start_age: base_probability
    - Increases with age (roughly doubles every 5 years)
    """
    if age < config.start_age or age > config.end_age:
        return 0.0
    years_into = age - config.start_age
    # Exponential increase: probability doubles every 5 years
    return min(0.15, config.base_probability * (2 ** (years_into / 5)))


# ---------------------------------------------------------------------------
# Reverse solver
# ---------------------------------------------------------------------------
@dataclass
class SolverResult:
    """Result of a reverse solver run."""
    lever_name: str
    lever_value: float          # the value that achieves target
    target_success_rate: float
    actual_success_rate: float
    median_final_nw: float
    iterations: int
    converged: bool
    message: str = ""


def reverse_solve(
    evaluation_fn: Callable[[float], float],
    lever_name: str,
    target_success_rate: float = 0.90,
    min_value: float = 0.0,
    max_value: float = 1_000_000,
    tolerance: float = 0.01,
    max_iterations: int = 50,
) -> SolverResult:
    """Binary search for the lever value that achieves target success rate."""
    lo, hi = min_value, max_value
    best_value = (lo + hi) / 2
    best_rate = 0.0
    converged = False
    i = 0

    for i in range(max_iterations):
        mid = (lo + hi) / 2
        rate = evaluation_fn(mid)
        best_rate = rate
        best_value = mid

        if abs(rate - target_success_rate) <= tolerance:
            converged = True
            break

        if rate < target_success_rate:
            lo = mid
        else:
            hi = mid

    message = (
        f"Found {lever_name}={best_value:,.0f} → "
        f"{best_rate:.1%} success (target: {target_success_rate:.1%})"
        if converged else
        f"Did not converge after {max_iterations} iterations. "
        f"Best: {lever_name}={best_value:,.0f} → {best_rate:.1%}"
    )

    return SolverResult(
        lever_name=lever_name,
        lever_value=best_value,
        target_success_rate=target_success_rate,
        actual_success_rate=best_rate,
        median_final_nw=0,
        iterations=min(max_iterations, i + 1),
        converged=converged,
        message=message,
    )


def solve_retirement_age(
    mc_evaluation_fn: Callable[[int], float],
    target_success: float = 0.90,
    min_age: int = 30,
    max_age: int = 70,
) -> SolverResult:
    """Find the earliest retirement age that achieves target success rate."""

    def age_fn(age: float) -> float:
        return mc_evaluation_fn(int(age))

    return reverse_solve(
        evaluation_fn=age_fn,
        lever_name="retirement_age",
        target_success_rate=target_success,
        min_value=float(min_age),
        max_value=float(max_age),
        tolerance=0.02,
    )


def solve_savings_rate(
    mc_evaluation_fn: Callable[[float], float],
    target_success: float = 0.90,
    min_rate: float = 0.0,
    max_rate: float = 0.50,
) -> SolverResult:
    """Find the minimum savings rate that achieves target success rate."""

    def rate_fn(rate: float) -> float:
        return mc_evaluation_fn(rate)

    return reverse_solve(
        evaluation_fn=rate_fn,
        lever_name="savings_rate",
        target_success_rate=target_success,
        min_value=min_rate,
        max_value=max_rate,
        tolerance=0.01,
    )


def solve_spending(
    mc_evaluation_fn: Callable[[float], float],
    target_success: float = 0.90,
    min_spending: float = 30_000,
    max_spending: float = 300_000,
) -> SolverResult:
    """Find the maximum spending that achieves target success rate."""

    def spend_fn(amount: float) -> float:
        return mc_evaluation_fn(amount)

    return reverse_solve(
        evaluation_fn=spend_fn,
        lever_name="annual_spending",
        target_success_rate=target_success,
        min_value=min_spending,
        max_value=max_spending,
        tolerance=0.02,
    )
