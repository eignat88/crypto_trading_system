from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class PaperState:
    """Persistent state for spot paper trading."""

    balances: dict[str, Decimal] = field(default_factory=dict)
    orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    executions: list[dict[str, Any]] = field(default_factory=list)
    positions: dict[str, Decimal] = field(default_factory=dict)

    def get_balance(self, asset: str) -> Decimal:
        return self.balances.get(asset, Decimal("0"))
