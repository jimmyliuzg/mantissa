"""Typed state carried through a yearly projection."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SimulationState:
    """Mutable, serializable state for one simulated year.

    Domain-specific objects remain optional so this boundary can be introduced
    without breaking the existing planner API.
    """
    year: int
    primary_age: int
    spouse_age: int
    balances: Dict[str, float] = field(default_factory=dict)
    liabilities: Dict[str, float] = field(default_factory=dict)
    tax_lots: Any = None
    income: Dict[str, Any] = field(default_factory=dict)
    expenses: Dict[str, Any] = field(default_factory=dict)
    withdrawals: List[Any] = field(default_factory=list)
    contributions: Dict[str, float] = field(default_factory=dict)
    taxes: float = 0.0
    healthcare: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def total_assets(self) -> float:
        return sum(value for value in self.balances.values() if value > 0)

    def total_liabilities(self) -> float:
        return sum(abs(value) for value in self.liabilities.values() if value < 0)

    def net_worth(self) -> float:
        return self.total_assets() - self.total_liabilities()

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def as_dict(self) -> dict:
        return {
            "year": self.year,
            "primary_age": self.primary_age,
            "spouse_age": self.spouse_age,
            "balances": dict(self.balances),
            "liabilities": dict(self.liabilities),
            "income": self.income,
            "expenses": self.expenses,
            "withdrawals": [getattr(item, "__dict__", item) for item in self.withdrawals],
            "contributions": dict(self.contributions),
            "taxes": self.taxes,
            "healthcare": self.healthcare,
            "warnings": list(self.warnings),
            "events": list(self.events),
            "total_assets": self.total_assets(),
            "total_liabilities": self.total_liabilities(),
            "net_worth": self.net_worth(),
        }
