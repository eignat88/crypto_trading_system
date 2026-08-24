"""Universe management for the scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UniverseConfig:
    """Scanner universe configuration."""
    symbols: list[str] = field(default_factory=lambda: [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT",
        "ADAUSDT", "LINKUSDT", "AVAXUSDT",
    ])
    min_24h_quote_volume: float = 10_000_000
    timeframe: str = "1h"
    min_candles: int = 250


DEFAULT_UNIVERSE = UniverseConfig()
