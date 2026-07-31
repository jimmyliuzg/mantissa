"""Shared projection orchestration helpers.

These helpers deliberately contain no tax or investment policy. They provide a
single boundary for yearly context and state creation used by deterministic and
stochastic projections while the legacy planner facade remains intact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .state import SimulationState


@dataclass(frozen=True)
class YearContext:
    """Calendar and household context for one projection year."""
    year: int
    primary_age: int
    spouse_age: int
    years_from_base: int

    @property
    def younger_age(self) -> int:
        return min(self.primary_age, self.spouse_age)


def make_year_context(year: int, start_year: int,
                      primary_birth_year: int,
                      spouse_birth_year: int) -> YearContext:
    return YearContext(
        year=year,
        primary_age=year - primary_birth_year,
        spouse_age=year - spouse_birth_year,
        years_from_base=year - start_year,
    )


def make_state(context: YearContext, balances: Optional[Dict[str, float]] = None,
               liabilities: Optional[Dict[str, float]] = None) -> SimulationState:
    """Create a state whose balance dictionaries can be shared with legacy code."""
    return SimulationState(
        year=context.year,
        primary_age=context.primary_age,
        spouse_age=context.spouse_age,
        balances=balances if balances is not None else {},
        liabilities=liabilities if liabilities is not None else {},
    )


def record_projection_state(state: SimulationState, *, income=None,
                            expenses=None, taxes: float = 0.0,
                            withdrawals=None, contributions=None,
                            healthcare=None) -> dict:
    """Record common yearly fields and return the serialized state."""
    if income is not None:
        state.income = income
    if expenses is not None:
        state.expenses = expenses
    if withdrawals is not None:
        state.withdrawals = withdrawals
    if contributions is not None:
        state.contributions = contributions
    if healthcare is not None:
        state.healthcare = healthcare
    state.taxes = taxes
    return state.as_dict()
