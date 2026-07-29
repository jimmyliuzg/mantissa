"""
Phase 1: Tax lot tracking for accurate capital gains.

Provides:
- TaxLot: individual purchase lot (date, shares, basis, holding period)
- TaxLotTracker: per-account lot management
- Liquidation algorithms: FIFO, HIFO, Specific ID, Minimum Gain
- §121 exclusion for primary residence sales
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple


@dataclass
class TaxLot:
    """A single purchase lot with its cost basis and holding period."""
    lot_id: str = ""
    account_id: str = ""
    purchase_date: date = field(default_factory=date.today)
    shares: float = 0.0
    cost_basis_per_share: float = 0.0
    asset_class: str = "equity"  # "equity", "bond", "mixed"

    def __post_init__(self):
        if not self.lot_id:
            self.lot_id = str(uuid.uuid4())[:8]

    @property
    def total_cost(self) -> float:
        return self.shares * self.cost_basis_per_share

    def holding_period_years(self, as_of: date) -> float:
        """Holding period in years (for LTCG qualification)."""
        delta = as_of - self.purchase_date
        return delta.days / 365.25

    def is_long_term(self, as_of: date) -> bool:
        """True if held > 1 year (qualifies for LTCG rates)."""
        return self.holding_period_years(as_of) > 1.0

    def split(self, shares_to_sell: float) -> Tuple[TaxLot, TaxLot]:
        """Split this lot into (sold, remaining)."""
        sold = TaxLot(
            lot_id=self.lot_id,
            account_id=self.account_id,
            purchase_date=self.purchase_date,
            shares=shares_to_sell,
            cost_basis_per_share=self.cost_basis_per_share,
            asset_class=self.asset_class,
        )
        remaining = TaxLot(
            lot_id=f"{self.lot_id}_r",
            account_id=self.account_id,
            purchase_date=self.purchase_date,
            shares=self.shares - shares_to_sell,
            cost_basis_per_share=self.cost_basis_per_share,
            asset_class=self.asset_class,
        )
        return sold, remaining


@dataclass
class LiquidationResult:
    """Result of liquidating shares from a tax lot."""
    lots_sold: List[TaxLot]
    total_shares: float
    total_proceeds: float
    total_cost_basis: float
    short_term_gain: float
    long_term_gain: float
    total_gain: float

    @property
    def tax_character(self) -> str:
        if self.short_term_gain > 0 and self.long_term_gain > 0:
            return "mixed"
        elif self.short_term_gain > 0:
            return "ordinary"  # short-term = ordinary rates
        else:
            return "capital_gains"


class TaxLotTracker:
    """Manages tax lots across accounts.

    Each account maintains a list of lots. When shares are sold,
    the liquidation algorithm selects which lots to sell.
    """

    def __init__(self):
        self.lots: Dict[str, List[TaxLot]] = {}  # account_id → list of lots

    def add_lot(self, account_id: str, lot: TaxLot):
        """Add a purchase lot to an account."""
        if account_id not in self.lots:
            self.lots[account_id] = []
        lot.account_id = account_id
        self.lots[account_id].append(lot)

    def add_purchase(self, account_id: str, shares: float,
                     cost_per_share: float, purchase_date: date,
                     asset_class: str = "equity"):
        """Convenience method to record a purchase."""
        self.add_lot(account_id, TaxLot(
            account_id=account_id,
            purchase_date=purchase_date,
            shares=shares,
            cost_basis_per_share=cost_per_share,
            asset_class=asset_class,
        ))

    def total_shares(self, account_id: str) -> float:
        return sum(l.shares for l in self.lots.get(account_id, []))

    def total_basis(self, account_id: str) -> float:
        return sum(l.total_cost for l in self.lots.get(account_id, []))

    def get_basis(self, account_id: str, default: float = 0.0) -> float:
        """Get total cost basis for an account (compatibility alias)."""
        return self.total_basis(account_id) or default

    def get_lots(self, account_id: str) -> List[TaxLot]:
        return list(self.lots.get(account_id, []))

    def liquidate(
        self,
        account_id: str,
        shares_to_sell: float,
        current_price: float,
        algorithm: str = "hifo",
        sale_date: Optional[date] = None,
    ) -> LiquidationResult:
        """Liquidate shares from an account. Requires current_price.

        This is a convenience wrapper around liquidate_with_price().
        Price is required — silent zero-gain reporting is a bug.
        """
        if current_price < 0:
            raise ValueError("current_price must be non-negative")
        return self.liquidate_with_price(
            account_id=account_id,
            shares_to_sell=shares_to_sell,
            current_price=current_price,
            algorithm=algorithm,
            sale_date=sale_date,
        )

    def liquidate_with_price(
        self,
        account_id: str,
        shares_to_sell: float,
        current_price: float,
        algorithm: str = "hifo",
        sale_date: Optional[date] = None,
    ) -> LiquidationResult:
        """Liquidate shares with gain calculation using current price."""
        if sale_date is None:
            sale_date = date.today()

        available = list(self.lots.get(account_id, []))
        if not available:
            return LiquidationResult(
                lots_sold=[], total_shares=0, total_proceeds=0,
                total_cost_basis=0, short_term_gain=0,
                long_term_gain=0, total_gain=0,
            )

        # Sort lots by algorithm
        if algorithm == "fifo":
            sorted_lots = sorted(available, key=lambda l: l.purchase_date)
        elif algorithm == "hifo":
            # Highest cost basis first → lowest gain
            sorted_lots = sorted(available, key=lambda l: l.cost_basis_per_share, reverse=True)
        elif algorithm == "lifo":
            sorted_lots = sorted(available, key=lambda l: l.purchase_date, reverse=True)
        elif algorithm == "min_gain":
            # Sell lots closest to current price first (smallest gain)
            sorted_lots = sorted(available,
                key=lambda l: abs(current_price - l.cost_basis_per_share))
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

        # Select lots
        sold_lots = []
        remaining = shares_to_sell

        for lot in sorted_lots:
            if remaining <= 0:
                break
            if lot.shares <= 0:
                continue

            sell_shares = min(remaining, lot.shares)
            sold, remainder = lot.split(sell_shares)
            sold_lots.append(sold)
            lot.shares = remainder.shares
            remaining -= sell_shares

        # Remove empty lots
        self.lots[account_id] = [l for l in self.lots.get(account_id, []) if l.shares > 0]

        # Compute gains
        total_shares = sum(l.shares for l in sold_lots)
        total_proceeds = total_shares * current_price
        total_basis = sum(l.total_cost for l in sold_lots)
        total_gain = total_proceeds - total_basis

        # Split into short-term and long-term
        short_term_gain = 0.0
        long_term_gain = 0.0
        for lot in sold_lots:
            gain = lot.shares * (current_price - lot.cost_basis_per_share)
            if lot.is_long_term(sale_date):
                long_term_gain += gain
            else:
                short_term_gain += gain

        return LiquidationResult(
            lots_sold=sold_lots,
            total_shares=total_shares,
            total_proceeds=total_proceeds,
            total_cost_basis=total_basis,
            short_term_gain=short_term_gain,
            long_term_gain=long_term_gain,
            total_gain=total_gain,
        )

    def sell_specific(
        self,
        account_id: str,
        shares_by_lot: dict,
        current_price: float,
        sale_date: Optional[date] = None,
    ) -> LiquidationResult:
        """Sell specific lots by ID with partial share support.

        Args:
            shares_by_lot: dict mapping lot_id -> shares to sell.
                           Can sell partial lots (e.g., {"lot_abc": 50}).
        """
        if sale_date is None:
            sale_date = date.today()

        available = self.lots.get(account_id, [])
        sold_lots = []
        updated_lots = []

        for lot in available:
            if lot.lot_id in shares_by_lot:
                requested = shares_by_lot[lot.lot_id]
                if requested <= 0:
                    raise ValueError(f"Invalid share quantity for lot {lot.lot_id}")
                if requested > lot.shares + 0.01:
                    raise ValueError(
                        f"Requested {requested} shares for lot {lot.lot_id} "
                        f"but only {lot.shares} available"
                    )
                sold, remainder = lot.split(requested)
                sold_lots.append(sold)
                if remainder.shares > 0.01:
                    updated_lots.append(remainder)
            else:
                updated_lots.append(lot)

        self.lots[account_id] = updated_lots

        # Compute gains
        total_shares = sum(l.shares for l in sold_lots)
        total_proceeds = total_shares * current_price
        total_basis = sum(l.total_cost for l in sold_lots)
        total_gain = total_proceeds - total_basis

        short_term_gain = 0.0
        long_term_gain = 0.0
        for lot in sold_lots:
            gain = lot.shares * (current_price - lot.cost_basis_per_share)
            if lot.is_long_term(sale_date):
                long_term_gain += gain
            else:
                short_term_gain += gain

        return LiquidationResult(
            lots_sold=sold_lots,
            total_shares=total_shares,
            total_proceeds=total_proceeds,
            total_cost_basis=total_basis,
            short_term_gain=short_term_gain,
            long_term_gain=long_term_gain,
            total_gain=total_gain,
        )


# ---------------------------------------------------------------------------
# §121 exclusion for primary residence
# ---------------------------------------------------------------------------
def calculate_121_exclusion(
    sale_price: float,
    cost_basis: float,
    filing_status: str = "MFJ",
    years_owned: float = 5.0,
    years_lived: float = 5.0,
) -> Tuple[float, float]:
    """Calculate IRC §121 primary residence exclusion.

    Returns (excluded_gain, taxable_gain).
    """
    # Must have owned and lived in home 2 of last 5 years
    if years_owned < 2.0 or years_lived < 2.0:
        return 0.0, max(0.0, sale_price - cost_basis)

    gross_gain = max(0.0, sale_price - cost_basis)

    if filing_status in ("MFJ", "QSS"):
        exclusion = 500_000
    else:
        exclusion = 250_000

    excluded = min(gross_gain, exclusion)
    taxable = gross_gain - excluded

    return excluded, taxable
