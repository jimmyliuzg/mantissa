"""
Monthly event timing for ACA, IRMAA, and RMD.

The annual cash-flow model runs at year granularity, but some tax/insurance
events have intra-year timing that matters:

- ACA subsidies: monthly, based on projected annual MAGI
- IRMAA: 2-year lookback, affects Part B/D premiums
- RMDs: must be taken by Dec 31 (first RMD can delay to April 1)

This module provides a lightweight monthly event framework that the engine
can call during the year simulation to get more accurate timing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class MonthlyEvent:
    """A discrete event that occurs in a specific month."""
    month: int             # 1-12
    name: str              # e.g. "aca_subsidy", "irmaa_assessment", "rmd_deadline"
    amount: float = 0.0    # dollar impact (positive = income/cost, negative = savings)
    metadata: Dict = field(default_factory=dict)


def calculate_monthly_aca_subsidy(
    annual_subsidy: float,
    months_eligible: int = 12,
) -> List[MonthlyEvent]:
    """Convert annual ACA subsidy into monthly premium tax credit events.

    ACA subsidies are applied monthly — the marketplace advances the credit
    based on projected annual income. At tax time, there's a reconciliation.
    """
    if annual_subsidy <= 0 or months_eligible <= 0:
        return []

    monthly_credit = annual_subsidy / months_eligible
    events = []
    for m in range(1, months_eligible + 1):
        events.append(MonthlyEvent(
            month=m,
            name="aca_subsidy",
            amount=-monthly_credit,  # negative = reduces cost
            metadata={"type": "premium_tax_credit"},
        ))
    return events


def calculate_irmaa_assessment(
    magi_two_years_prior: float,
    annual_surcharge: float,
    current_age: int,
) -> List[MonthlyEvent]:
    """Convert annual IRMAA into monthly Medicare premium surcharges.

    IRMAA is assessed monthly by CMS based on MAGI from 2 years ago.
    If MAGI drops, the surcharge can be adjusted retroactively (life-changing
    event).
    """
    if annual_surcharge <= 0 or current_age < 65:
        return []

    monthly_surcharge = annual_surcharge / 12
    events = []
    for m in range(1, 13):
        events.append(MonthlyEvent(
            month=m,
            name="irmaa_surcharge",
            amount=monthly_surcharge,  # positive = additional cost
            metadata={
                "magi_lookback": magi_two_years_prior,
                "annual_total": annual_surcharge,
            },
        ))
    return events


def calculate_rmd_events(
    account_balances: Dict[str, float],
    age: int,
    year: int,
    rmd_table: Optional[Dict[int, float]] = None,
) -> List[MonthlyEvent]:
    """Generate RMD (Required Minimum Distribution) events.

    RMDs must be taken by Dec 31 of each year (first RMD can delay to
    April 1 of the following year). The distribution is taxable income.

    Args:
        account_balances: dict of account_id → balance (pre-tax accounts only)
        age: account owner's age at end of year
        year: calendar year
        rmd_table: age → distribution period (from IRS Uniform Lifetime Table)
    """
    if age < 73:  # SECURE 2.0 Act: RMD age is 73
        return []

    if rmd_table is None:
        # Default IRS Uniform Lifetime Table (2024)
        rmd_table = {
            73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9,
            78: 22.0, 79: 21.1, 80: 20.2, 81: 19.4, 82: 18.5,
            83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2, 87: 14.4,
            88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8,
            93: 10.1, 94: 9.5, 95: 8.9,
        }

    period = rmd_table.get(age)
    if period is None:
        return []

    events = []
    for account_id, balance in account_balances.items():
        if balance <= 0:
            continue
        rmd_amount = balance / period
        events.append(MonthlyEvent(
            month=12,  # Deadline is Dec 31
            name="rmd",
            amount=rmd_amount,
            metadata={
                "account_id": account_id,
                "balance": balance,
                "distribution_period": period,
                "age": age,
                "is_first_rmd": age == 73,
                "can_delay_to_april": age == 73,  # First RMD can delay to April 1 next year
            },
        ))

    return events


def process_year_events(
    year: int,
    age: int,
    magi: float,
    magi_two_years_prior: float,
    irmaa_annual: float,
    aca_annual_subsidy: float,
    aca_months_eligible: int,
    pre_tax_balances: Dict[str, float],
    filing_status=None,
) -> List[MonthlyEvent]:
    """Process all monthly events for a given year.

    Returns a sorted list of MonthlyEvent for the year.
    """
    events = []

    # ACA subsidy (monthly)
    events.extend(calculate_monthly_aca_subsidy(aca_annual_subsidy, aca_months_eligible))

    # IRMAA (monthly, based on 2-year-ago MAGI)
    events.extend(calculate_irmaa_assessment(magi_two_years_prior, irmaa_annual, age))

    # RMD (Dec 31 deadline)
    events.extend(calculate_rmd_events(pre_tax_balances, age, year))

    # Sort by month
    events.sort(key=lambda e: e.month)

    return events
