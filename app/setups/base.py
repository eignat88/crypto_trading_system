"""Base setup detector interface and shared utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class SetupType(StrEnum):
    COMPRESSION = "COMPRESSION"
    BREAKOUT = "BREAKOUT"
    RETEST_READY = "RETEST_READY"
    FAILED_BREAKOUT = "FAILED_BREAKOUT"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    LONG_CANDIDATE = "LONG_CANDIDATE"
    SHORT_CANDIDATE = "SHORT_CANDIDATE"


@dataclass
class SetupSignal:
    """A detected setup signal from a detector."""
    symbol: str
    timeframe: str
    setup_type: SetupType
    direction: Direction
    detected_at: datetime
    current_price: Decimal
    score: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)
    candle_timestamp: datetime | None = None


@dataclass
class CandleData:
    """Normalized candle data for detector input."""
    symbol: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class IndicatorSnapshot:
    """Indicator values at a point in time."""
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    ema200: Decimal | None = None
    atr: Decimal | None = None
    atr_period: int = 14
    volume_ma20: Decimal | None = None


class BaseSetupDetector(ABC):
    """Abstract base class for all setup detectors."""

    @property
    @abstractmethod
    def setup_type(self) -> SetupType:
        """Return the setup type this detector identifies."""

    @abstractmethod
    def detect(
        self,
        symbol: str,
        timeframe: str,
        candles: list[CandleData],
        indicators: IndicatorSnapshot,
        state: dict[str, Any] | None = None,
    ) -> SetupSignal | None:
        """Analyze candles and indicators to detect a setup."""

    @staticmethod
    def _high_range(candles: list[CandleData], n: int) -> Decimal | None:
        """Get max high over last n candles."""
        if len(candles) < n:
            return None
        return max(c.high for c in candles[-n:])

    @staticmethod
    def _low_range(candles: list[CandleData], n: int) -> Decimal | None:
        """Get min low over last n candles."""
        if len(candles) < n:
            return None
        return min(c.low for c in candles[-n:])

    @staticmethod
    def _range(candles: list[CandleData], n: int) -> Decimal | None:
        """Get price range (max_high - min_low) over last n candles."""
        high = BaseSetupDetector._high_range(candles, n)
        low = BaseSetupDetector._low_range(candles, n)
        if high is None or low is None:
            return None
        return high - low
