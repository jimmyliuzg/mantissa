"""
Phase 0 fixes — wire dead config into simulation.

Fixes:
- 0.1: housing_events — buy/sell/refinance into simulation timeline
- 0.2: roth_conversions — execute in simulation loop (before withdrawals)
- 0.3: medical_inflation — escalate healthcare costs at medical rate

These are correctness fixes for config that is parsed but silently ignored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# 0.1 Housing event processing
# ---------------------------------------------------------------------------
@dataclass
class HousingEventResult:
    """Result of processing a housing event."""
    event_id: str
    event_type: str        # "sale", "purchase", "refinance"
    account_delta: float   # change in account balance (+ = inflow)
    mortgage_delta: float  # change in mortgage balance (+ = new debt)
    gain_realized: float   # capital gain from sale (may be excluded)
    tax_due: float         # tax on realized gain
    property_account_change: float  # change in real_estate account
    taxable_gain: float = 0.0
    funding_shortfall: float = 0.0
    sale_proceeds: float = 0.0
    purchase_funding: float = 0.0


def process_housing_event(
    event,  # HousingEvent from models.py
    year: int,
    balances: Dict[str, float],
    mortgage_balances: Dict[str, float],
    cost_basis: float,  # basis in property being sold
    filing_status: str = "MFJ",
    state: str = "CA",
    mortgage_property_map: Optional[Dict[str, str]] = None,
    event_mortgage_terms: Optional[Dict[str, tuple]] = None,
    defer_tax: bool = False,
) -> HousingEventResult:
    """Process a housing event (buy/sell/refinance) in place.

    Mutates *balances* and *mortgage_balances* directly.  Handles:
    - Sale: pays off only the mortgage(s) secured by ``event.property_id``
      (all mortgages when property_id is empty), routes net proceeds to
      ``goes_to_account``, and removes the property balance.
    - Purchase: funds the down payment from ``funding_account``, adds the
      new property value, and registers a new amortizing mortgage in
      *event_mortgage_terms* (rate, monthly payment, start date).
    """
    event_year = event.event_date.year
    if event_year != year:
        return HousingEventResult(
            event_id=event.id, event_type="none",
            account_delta=0, mortgage_delta=0, gain_realized=0,
            tax_due=0, property_account_change=0,
        )

    taxable_gain = 0.0
    funding_shortfall = 0.0
    property_delta = 0.0
    mortgage_delta = 0.0
    account_delta = 0.0
    gain_realized = 0.0
    tax_due = 0.0
    event_type = "none"

    # SALE
    if event.sale_price > 0:
        event_type = "sale"

        # Capital gain (IRC §121 exclusion: $250k single / $500k MFJ)
        gross_gain = event.sale_price - event.selling_costs - cost_basis
        if filing_status in ("MFJ", "QSS", "mfj", "qss"):
            exclusion = 500_000
        else:
            exclusion = 250_000
        exclusion = exclusion if event.exclusion_eligible else 0.0
        taxable_gain = max(0.0, gross_gain - exclusion)
        gain_realized = gross_gain  # total gain (before exclusion)

        # Tax on gain (simplified — 15% LTCG + CA ~9.3%)
        if taxable_gain > 0 and not defer_tax:
            tax_due = taxable_gain * (0.15 + (0.093 if state.upper() == "CA" else 0.0))

        proceeds = event.sale_price - event.selling_costs - tax_due

        # Pay off only the mortgage(s) secured by this property
        payoff = 0.0
        for mort_id, mort_balance in list(mortgage_balances.items()):
            if mort_balance <= 0:
                continue
            if event.property_id and mortgage_property_map:
                if mortgage_property_map.get(mort_id) != event.property_id:
                    continue
            payoff += mort_balance
            mortgage_balances[mort_id] = 0.0

        # Net proceeds (after payoff) go to the target account
        mortgage_delta -= payoff
        net = proceeds - payoff
        goes_to = event.goes_to_account or "joint_brokerage"
        balances[goes_to] = balances.get(goes_to, 0.0) + net
        account_delta += net

        # Remove the sold property from balances
        if event.property_id:
            old_balance = balances.get(event.property_id, 0.0)
            balances[event.property_id] = 0.0
            property_delta -= old_balance
        else:
            balances.pop("real_estate", None)

    # PURCHASE
    if event.purchase_price > 0:
        event_type = "trade_up" if event_type == "sale" else "purchase"

        funding = event.funding_account or "joint_brokerage"
        # Full purchase funding must equal equity plus mortgage; a shortage cannot create free home equity.
        required_equity = event.purchase_price - event.mortgage_amount + event.purchase_costs
        funding_shortfall = max(0.0, required_equity - max(0.0, balances.get(funding, 0.0)))
        down = required_equity
        balances[funding] = balances.get(funding, 0.0) - down
        account_delta -= down

        # Add the new property value
        prop_id = event.property_id or f"property_{event.id}"
        balances[prop_id] = balances.get(prop_id, 0.0) + event.purchase_price
        property_delta += event.purchase_price

        # Register the new mortgage for monthly amortization
        if event.mortgage_amount > 0:
            mort_id = event.new_mortgage_id or f"{event.id}_mortgage"
            mortgage_balances[mort_id] = event.mortgage_amount
            mortgage_delta += event.mortgage_amount
            if event_mortgage_terms is not None:
                rate = event.mortgage_rate
                monthly_rate = rate / 12
                n = max(1, event.mortgage_term_years * 12)
                if monthly_rate > 0:
                    annuity = (1 + monthly_rate) ** n
                    payment = (
                        event.mortgage_amount * monthly_rate * annuity
                        / (annuity - 1) if annuity != 1
                        else event.mortgage_amount / n
                    )
                else:
                    payment = event.mortgage_amount / n
                event_mortgage_terms[mort_id] = (
                    rate, payment, event.event_date)

    return HousingEventResult(
        event_id=event.id,
        event_type=event_type,
        account_delta=account_delta,
        mortgage_delta=mortgage_delta,
        gain_realized=gain_realized,
        tax_due=tax_due,
        property_account_change=property_delta,
        taxable_gain=taxable_gain,
        funding_shortfall=funding_shortfall,
        sale_proceeds=net if event.sale_price > 0 else 0.0,
        purchase_funding=required_equity if event.purchase_price > 0 else 0.0,
    )


# ---------------------------------------------------------------------------
# 0.2 Roth conversion processing
# ---------------------------------------------------------------------------
@dataclass
class RothConversionResult:
    """Result of processing Roth conversions in a year."""
    total_converted: float
    ordinary_income_added: float  # conversions are taxable events
    conversions: List[dict]  # [{source, target, amount}]


def _year_active_fraction(start_date: date, end_date: date, year: int) -> float:
    """Fraction of *year* during which a dated stream is active.

    Mirrors engine._year_active_fraction (kept local to avoid a circular
    import).  Jan-1 end dates are exclusive: a window ending 2033-01-01
    is inactive in 2033.
    """
    from datetime import timedelta
    effective_end = end_date
    if end_date.month == 1 and end_date.day == 1:
        effective_end = end_date - timedelta(days=1)
    if year < start_date.year or year > effective_end.year:
        return 0.0
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    days_in_year = (year_end - year_start).days + 1
    active_start = max(start_date, year_start)
    active_end = min(effective_end, year_end)
    if active_end < active_start:
        return 0.0
    active_days = (active_end - active_start).days + 1
    return active_days / days_in_year


def process_roth_conversions(
    conversions,  # List[RothConversion] from models.py
    year: int,
    balances: Dict[str, float],
    max_conversion: float = float('inf'),
    rmd_reserves: Optional[Dict[str, float]] = None,
) -> RothConversionResult:
    """Process all active Roth conversions for a year.

    IRS rules:
    1. RMD must be satisfied first (not handled here — caller's responsibility)
    2. Conversion amount is added to ordinary income for the year
    3. Source account is debited, target account is credited
    """
    total = 0.0
    details = []

    for rc in conversions:
        # Check if conversion is active this year (end-exclusive:
        # a window ending 2033-01-01 is inactive in 2033).
        fraction = _year_active_fraction(rc.start_date, rc.end_date, year)
        if fraction <= 0:
            continue
        amount = min(rc.annual_amount, max_conversion) * fraction
        if amount <= 0:
            continue

        # Check source has enough
        source_balance = balances.get(rc.source_account, 0)
        actual = min(amount, max(0.0, source_balance - (rmd_reserves or {}).get(rc.source_account, 0.0)))
        if actual <= 0:
            continue

        # Execute conversion
        balances[rc.source_account] = source_balance - actual
        target_balance = balances.get(rc.target_account, 0)
        balances[rc.target_account] = target_balance + actual

        total += actual
        details.append({
            "source": rc.source_account,
            "target": rc.target_account,
            "amount": actual,
        })

    return RothConversionResult(
        total_converted=total,
        ordinary_income_added=total,  # conversions are taxable
        conversions=details,
    )


# ---------------------------------------------------------------------------
# 0.3 Medical inflation application
# ---------------------------------------------------------------------------
def apply_medical_inflation(
    base_expenses: float,
    year: int,
    start_year: int,
    general_inflation: float = 0.025,
    medical_inflation: float = 0.034,
) -> float:
    """Grow healthcare expenses at medical inflation rate.

    Since the model is in real dollars, only the EXCESS over general
    inflation should compound. Medical costs grow ~0.9% faster than CPI.
    """
    years = year - start_year
    if years <= 0:
        return base_expenses

    # Excess inflation compounds annually
    excess_rate = medical_inflation - general_inflation
    factor = (1.0 + excess_rate) ** years
    return base_expenses * factor


def process_medical_expenses(
    expenses: List,  # List[Expense]
    year: int,
    start_year: int,
    general_inflation: float = 0.025,
    medical_inflation: float = 0.034,
) -> float:
    """Apply medical inflation to healthcare-tagged expenses.

    Returns the total additional cost from medical inflation.
    """
    additional = 0.0
    for exp in expenses:
        if exp.category == "healthcare":
            # The base amount is already in the expense calculation
            # We add the excess medical inflation on top
            years = year - start_year
            excess_rate = medical_inflation - general_inflation
            factor = (1.0 + excess_rate) ** years - 1.0  # delta from base
            additional += exp.monthly_amount * 12 * factor

    return additional
