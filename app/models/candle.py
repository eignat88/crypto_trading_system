from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class Candle:
    """Normalized market candle used by paper trading."""

    symbol: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def validate(self) -> None:
        if self.close_time <= self.open_time:
            raise ValueError("Candle close_time must be after open_time")
        if self.high < max(self.open, self.close):
            raise ValueError("Invalid candle high")
        if self.low > min(self.open, self.close):
            raise ValueError("Invalid candle low")
