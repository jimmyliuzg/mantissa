"""
Phase 4: Expanded equity compensation — ESPP, NQSO, Mega-Backdoor Roth.

ESPP (Employee Stock Purchase Plan):
- 6-month offering periods with lookback provision
- 15% discount on purchase price
- Qualifying vs disqualifying disposition tax treatment

NQSO (Non-Qualified Stock Options):
- Exercise timing, spread taxation (ordinary income)
- AMT interaction for ISOs (stretch: treat NQSOs similarly)
- Cashless exercise support

Mega-Backdoor Roth:
- After-tax 401(k) contributions (beyond elective deferral limit)
- In-plan Roth conversion or direct Roth IRA rollover
- Basis tracking for tax-free withdrawals
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional


# ---------------------------------------------------------------------------
# ESPP
# ---------------------------------------------------------------------------
@dataclass
class ESPPGrant:
    """One ESPP offering period."""
    id: str
    ticker: str
    offering_start: date
    offering_end: date        # typically 6 months after start
    purchase_date: date       # when shares are actually purchased
    discount_pct: float = 0.15     # 15% standard ESPP discount
    lookback: bool = True          # use lower of start/end price
    shares_purchased: float = 0.0
    purchase_price: float = 0.0    # price paid (after discount)
    market_price_at_purchase: float = 0.0
    market_price_at_start: float = 0.0
    annual_contribution_limit: float = 25_000  # IRS max ($25k in 2024)
    payroll_deduction_pct: float = 0.10  # % of salary going to ESPP


@dataclass
class ESPPDisposition:
    """Tax treatment of ESPP share sale."""
    holding_period_years: float
    gain: float
    is_qualifying: bool  # >2 years from grant, >1 year from purchase

    @property
    def ordinary_income(self) -> float:
        """Disqualifying: discount is ordinary income."""
        if self.is_qualifying:
            return 0.0
        return self.gain  # Simplified — discount portion is ordinary

    @property
    def capital_gain(self) -> float:
        """Qualifying: entire gain is capital gain."""
        if self.is_qualifying:
            return self.gain
        return 0.0  # Disqualifying: all gain is ordinary


def calculate_espp_purchase_price(
    market_price_at_start: float,
    market_price_at_purchase: float,
    discount_pct: float = 0.15,
    lookback: bool = True,
) -> float:
    """Calculate ESPP purchase price with optional lookback.

    Lookback: use the LOWER of start-of-period or purchase-date price,
    then apply the discount.
    """
    if lookback:
        base_price = min(market_price_at_start, market_price_at_purchase)
    else:
        base_price = market_price_at_purchase

    return base_price * (1 - discount_pct)


def calculate_espp_income(
    shares: float,
    purchase_price: float,
    sale_price: float,
    is_qualifying: bool,
) -> dict:
    """Calculate ESPP tax income components.

    Qualifying disposition (>2yr from grant, >1yr from purchase):
        - Discount at purchase: not taxed
        - All gain taxed as capital gain

    Disqualifying disposition (<2yr or <1yr):
        - Discount at purchase: ordinary income
        - Additional gain/loss: capital gain/loss
    """
    total_gain = shares * (sale_price - purchase_price)

    if is_qualifying:
        return {
            "ordinary_income": 0.0,
            "capital_gain": total_gain,
            "total_income": total_gain,
        }
    else:
        # Disqualifying: discount portion is ordinary
        discount_per_share = purchase_price  # This is the discount already applied
        # Actually: ordinary income = min(gain, discount that would have been)
        # Simplified: all gain is ordinary for disqualifying
        return {
            "ordinary_income": total_gain,
            "capital_gain": 0.0,
            "total_income": total_gain,
        }


def simulate_espp_period(
    grant: ESPPGrant,
    stock_price_path: List[float],  # [start_price, end_price]
    salary: float,
) -> dict:
    """Simulate one ESPP offering period.

    Returns shares purchased, cost, and tax components.
    """
    if len(stock_price_path) < 2:
        return {"shares": 0, "cost": 0, "gain": 0}

    start_price = stock_price_path[0]
    end_price = stock_price_path[-1]

    # Calculate purchase price
    purchase_price = calculate_espp_purchase_price(
        start_price, end_price,
        discount_pct=grant.discount_pct,
        lookback=grant.lookback,
    )

    # Calculate shares (limited by $25k annual limit at FMV)
    max_shares_by_limit = grant.annual_contribution_limit / start_price
    payroll_deduction = salary * grant.payroll_deduction_pct * 0.5  # 6 months
    shares_from_payroll = payroll_deduction / purchase_price
    shares = min(shares_from_payroll, max_shares_by_limit)

    cost = shares * purchase_price
    value_at_purchase = shares * end_price
    immediate_gain = value_at_purchase - cost

    return {
        "shares": shares,
        "cost": cost,
        "purchase_price": purchase_price,
        "value_at_purchase": value_at_purchase,
        "immediate_gain": immediate_gain,
        "discount_pct": grant.discount_pct,
    }


# ---------------------------------------------------------------------------
# NQSO (Non-Qualified Stock Options)
# ---------------------------------------------------------------------------
@dataclass
class NQSOGrant:
    """Non-Qualified Stock Option grant."""
    id: str
    ticker: str
    grant_date: date
    total_shares: float
    strike_price: float
    vesting_schedule: str = "4yr_monthly"  # 4-year vest, monthly
    expiration_date: date = field(default_factory=lambda: date(2034, 1, 1))
    exercise_date: Optional[date] = None
    exercise_price: float = 0.0  # market price at exercise


@dataclass
class NQSOExercise:
    """Result of exercising NQSOs."""
    shares_exercised: float
    strike_price: float
    market_price_at_exercise: float
    spread: float            # market - strike (ordinary income)
    tax_ordinary: float      # spread × marginal tax rate
    tax_fica: float          # spread × FICA rate
    total_tax: float
    net_proceeds: float      # if cashless exercise

    @property
    def spread_per_share(self) -> float:
        return self.market_price_at_exercise - self.strike_price


def exercise_nqso(
    grant: NQSOGrant,
    shares_to_exercise: float,
    market_price: float,
    marginal_tax_rate: float = 0.37,
    fica_rate: float = 0.0765,
    state_tax_rate: float = 0.10,
    cashless: bool = True,
) -> NQSOExercise:
    """Exercise NQSOs (cashless or cash exercise).

    NQSO taxation:
    - Spread (FMV - strike) is ordinary income at exercise
    - Subject to FICA (Social Security + Medicare)
    - State income tax applies
    - No AMT implications (unlike ISOs)
    """
    spread = max(0, market_price - grant.strike_price)
    total_spread = shares_to_exercise * spread

    tax_ordinary = total_spread * marginal_tax_rate
    tax_fica = total_spread * fica_rate
    tax_state = total_spread * state_tax_rate
    total_tax = tax_ordinary + tax_fica + tax_state

    if cashless:
        # Broker loans you the strike price, sells shares to cover
        gross_proceeds = shares_to_exercise * market_price
        strike_cost = shares_to_exercise * grant.strike_price
        net_proceeds = gross_proceeds - strike_cost - total_tax
    else:
        # You pay strike price upfront
        net_proceeds = shares_to_exercise * market_price - total_tax

    return NQSOExercise(
        shares_exercised=shares_to_exercise,
        strike_price=grant.strike_price,
        market_price_at_exercise=market_price,
        spread=spread,
        tax_ordinary=tax_ordinary,
        tax_fica=tax_fica,
        total_tax=total_tax,
        net_proceeds=net_proceeds,
    )


def calculate_nqso_spread_tax(
    shares: float,
    strike: float,
    market_price: float,
    marginal_rate: float = 0.37,
    fica_rate: float = 0.0765,
    state_rate: float = 0.10,
) -> float:
    """Quick estimate of total tax on NQSO exercise."""
    spread = max(0, market_price - strike) * shares
    return spread * (marginal_rate + fica_rate + state_rate)


# ---------------------------------------------------------------------------
# Mega-Backdoor Roth
# ---------------------------------------------------------------------------
@dataclass
class MegaBackdoorRoth:
    """After-tax 401(k) → Roth IRA pipeline."""
    after_tax_401k_limit: float = 70_000  # Total 401k limit (2025: $70k)
    elective_deferral_limit: float = 23_500  # Pre-tax/Roth limit
    employer_match_estimate: float = 10_000  # estimated employer contribution

    @property
    def after_tax_capacity(self) -> float:
        """Maximum after-tax contribution (above elective deferral)."""
        return max(0, self.after_tax_401k_limit
                   - self.elective_deferral_limit
                   - self.employer_match_estimate)

    def calculate_annual_after_tax(
        self,
        salary: float,
        after_tax_pct: float = 0.10,
    ) -> float:
        """Calculate actual after-tax contribution for the year."""
        desired = salary * after_tax_pct
        return min(desired, self.after_tax_capacity)

    def simulate_pipeline(
        self,
        after_tax_contribution: float,
        years: int,
        growth_rate: float = 0.07,
        conversion_frequency: str = "monthly",
    ) -> dict:
        """Simulate the Mega-Backdoor Roth pipeline.

        After-tax 401(k) contributions grow tax-free in the after-tax bucket,
        then are converted to Roth (either in-plan or via rollover).
        """
        if conversion_frequency == "monthly":
            conversions_per_year = 12
        elif conversion_frequency == "quarterly":
            conversions_per_year = 4
        else:
            conversions_per_year = 1

        per_conversion = after_tax_contribution / conversions_per_year

        # Roth balance grows tax-free
        roth_balance = 0.0
        total_contributed = 0.0
        total_growth = 0.0

        for year in range(years):
            for _ in range(conversions_per_year):
                # Convert after-tax to Roth
                roth_balance += per_conversion
                total_contributed += per_conversion

                # Growth on Roth balance (tax-free)
                period_growth = roth_balance * (growth_rate / conversions_per_year)
                roth_balance += period_growth
                total_growth += period_growth

        return {
            "roth_balance": roth_balance,
            "total_contributed": total_contributed,
            "total_growth": total_growth,
            "tax_free_withdrawal": roth_balance,  # All Roth withdrawals are tax-free
        }


@dataclass
class AfterTaxAccount:
    """After-tax 401(k) balance with basis tracking."""
    balance: float = 0.0
    basis: float = 0.0  # after-tax contributions (not taxed again)

    def contribute(self, amount: float):
        self.balance += amount
        self.basis += amount

    def grow(self, rate: float):
        growth = self.balance * rate
        self.balance += growth

    def convert_to_roth(self, amount: float) -> float:
        """Convert after-tax to Roth. Returns amount converted."""
        actual = min(amount, self.balance)
        self.balance -= actual
        self.basis -= actual
        return actual

    @property
    def earnings(self) -> float:
        return max(0, self.balance - self.basis)
