"""Scanner result model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.setups.base import Direction, SetupType

SCANNER_VERSION = "1.0.0"
PARAMETERS_VERSION = "v1"


@dataclass
class ScannerResult:
    """Result of scanning a single symbol for setups."""
    symbol: str
    timeframe: str
    setup_type: SetupType
    direction: Direction
    score: Decimal
    detected_at: datetime
    current_price: Decimal
    atr: Decimal | None = None
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    ema200: Decimal | None = None
    volume: Decimal | None = None
    volume_ma20: Decimal | None = None
    breakout_level: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    scanner_version: str = SCANNER_VERSION
    parameters_version: str = PARAMETERS_VERSION
    candle_timestamp: datetime | None = None
