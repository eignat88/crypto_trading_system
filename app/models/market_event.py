from __future__ import annotations

from dataclasses import dataclass

from app.models.candle import Candle


@dataclass(frozen=True)
class MarketEvent:
    """Deterministic market event emitted by paper market data."""

    candle: Candle
    sequence: int
