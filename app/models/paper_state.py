from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperRuntimeState:
    """Serializable runtime state for paper trading recovery."""

    last_processed_timestamp: datetime | None = None
    last_market_sequence: int = 0
    cash_balance: Decimal = Decimal("0")

    def validate(self) -> None:
        if self.last_market_sequence < 0:
            raise ValueError("Market sequence cannot be negative")
        if self.cash_balance < 0:
            raise ValueError("Cash balance cannot be negative")
