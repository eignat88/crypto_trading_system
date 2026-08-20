from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models.candle import Candle


@dataclass(frozen=True)
class MarketEvent:
    """Deterministic market event emitted by paper market data."""

    candle: Candle
    sequence: int
    source: str = "paper"
    request_metadata: dict[str, Any] | None = None

    @property
    def symbol(self) -> str:
        return self.candle.symbol

    @property
    def timestamp(self) -> datetime:
        return self.candle.close_time

    @property
    def candle_close(self) -> Decimal:
        return self.candle.close
