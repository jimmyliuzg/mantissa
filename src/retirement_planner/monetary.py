"""
Monetary convention handling for the retirement planner.

Provides ``MonetaryPolicy`` which mediates between nominal and real
dollar conventions.  The engine stores all balances and flows in the
user's chosen convention (NOMINAL or REAL).  When interacting with
external systems that require nominal values (e.g. IRS tax brackets),
``MonetaryPolicy`` converts transparently.
"""
from __future__ import annotations

from .models import MonetaryConvention


class MonetaryPolicy:
    """Handles nominal/real conversion consistently.

    Parameters
    ----------
    convention:
        NOMINAL or REAL.
    base_year:
        The reference year whose purchasing power equals 1.0.
        Typically the first year of the simulation.
    inflation:
        Annual general inflation rate (decimal, e.g. 0.025 = 2.5 %).
        Used for compound conversion: ``factor = (1 + inflation)^(year - base_year)``.
    """

    def __init__(
        self,
        convention: MonetaryConvention,
        base_year: int,
        inflation: float = 0.025,
    ) -> None:
        self.convention = convention
        self.base_year = base_year
        self.inflation = inflation

    # ------------------------------------------------------------------
    # Core conversion helpers
    # ------------------------------------------------------------------
    def inflation_factor(self, year: int) -> float:
        """Compound inflation factor from *base_year* to *year*."""
        return (1.0 + self.inflation) ** (year - self.base_year)

    def to_nominal(self, real_value: float, year: int,
                   inflation: float | None = None) -> float:
        """Convert real dollars to nominal.

        In NOMINAL mode the input is already nominal — returned as-is.
        In REAL mode the input is real and gets inflated.
        """
        inf = inflation if inflation is not None else self.inflation
        if self.convention == MonetaryConvention.NOMINAL:
            return real_value  # already nominal
        factor = (1.0 + inf) ** (year - self.base_year)
        return real_value * factor

    def to_real(self, nominal_value: float, year: int,
                inflation: float | None = None) -> float:
        """Convert nominal dollars to real.

        In REAL mode the input is already real — returned as-is.
        In NOMINAL mode the input is nominal and gets deflated.
        """
        inf = inflation if inflation is not None else self.inflation
        if self.convention == MonetaryConvention.REAL:
            return nominal_value  # already real
        factor = (1.0 + inf) ** (year - self.base_year)
        if factor == 0.0:
            return nominal_value
        return nominal_value / factor

    def adjust_for_inflation(self, value: float, year: int,
                             inflation: float | None = None) -> float:
        """Adjust a base-year value for the convention.

        * NOMINAL mode: inflate so the value grows with the price level.
        * REAL mode: return unchanged (constant purchasing power).

        This is the main helper used by the engine to adjust expenses,
        income, and similar cash flows.
        """
        if self.convention == MonetaryConvention.NOMINAL:
            inf = inflation if inflation is not None else self.inflation
            factor = (1.0 + inf) ** (year - self.base_year)
            return value * factor
        return value  # real — no adjustment

    def portfolio_return_to_convention(
        self,
        real_return: float,
        inflation: float,
    ) -> float:
        """Convert a real portfolio return to the active convention.

        * NOMINAL: ``nominal_return = (1 + real) * (1 + inflation) - 1``
        * REAL: pass through unchanged.
        """
        if self.convention == MonetaryConvention.NOMINAL:
            return (1.0 + real_return) * (1.0 + inflation) - 1.0
        return real_return

    # ------------------------------------------------------------------
    # Tax helpers — taxes always computed on nominal income
    # ------------------------------------------------------------------
    def to_nominal_for_tax(self, value: float, year: int,
                           inflation: float | None = None) -> float:
        """Ensure *value* is nominal before passing to the tax engine.

        In NOMINAL mode this is a no-op.  In REAL mode the value is
        inflated to nominal so IRS bracket thresholds (which are
        nominal) apply correctly.
        """
        return self.to_nominal(value, year, inflation)

    def from_nominal_after_tax(self, tax_nominal: float, year: int,
                               inflation: float | None = None) -> float:
        """Convert a nominal tax amount back to the active convention.

        In NOMINAL mode this is a no-op (tax stays nominal).
        In REAL mode the tax is deflated so all engine values stay
        in real dollars.
        """
        if self.convention == MonetaryConvention.NOMINAL:
            return tax_nominal  # already in the right convention
        inf = inflation if inflation is not None else self.inflation
        factor = (1.0 + inf) ** (year - self.base_year)
        if factor == 0.0:
            return tax_nominal
        return tax_nominal / factor
