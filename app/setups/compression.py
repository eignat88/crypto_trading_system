"""COMPRESSION detector — identifies low volatility before potential breakout."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.setups.base import (
    BaseSetupDetector,
    CandleData,
    Direction,
    IndicatorSnapshot,
    SetupSignal,
    SetupType,
)

RANGE_COMPRESSION_THRESHOLD = Decimal("0.65")
DISTANCE_TO_HIGH_THRESHOLD = Decimal("1.0")


class CompressionDetector(BaseSetupDetector):
    """Detect volatility compression before potential impulse move."""

    @property
    def setup_type(self) -> SetupType:
        return SetupType.COMPRESSION

    def detect(
        self,
        symbol: str,
        timeframe: str,
        candles: list[CandleData],
        indicators: IndicatorSnapshot,
        state: dict[str, Any] | None = None,
    ) -> SetupSignal | None:
        if len(candles) < 50:
            return None

        atr = indicators.atr
        if atr is None or atr <= 0:
            return None

        range_10 = self._range(candles, 10)
        range_50 = self._range(candles, 50)

        if range_10 is None or range_50 is None or range_50 <= 0:
            return None

        range_ratio = range_10 / range_50
        if range_ratio >= RANGE_COMPRESSION_THRESHOLD:
            return None

        range_20 = self._range(candles, 20)
        if range_20 is None or range_20 <= 0:
            return None

        if not (range_10 < range_20):
            return None

        current = candles[-1]
        high_20 = self._high_range(candles, 20)
        low_20 = self._low_range(candles, 20)

        if high_20 is None or low_20 is None:
            return None

        distance_to_high = high_20 - current.close
        distance_to_low = current.close - low_20

        near_high = distance_to_high <= atr * DISTANCE_TO_HIGH_THRESHOLD
        near_low = distance_to_low <= atr * DISTANCE_TO_HIGH_THRESHOLD

        if not near_high and not near_low:
            return None

        direction = Direction.LONG_CANDIDATE if near_high else Direction.SHORT_CANDIDATE

        return SetupSignal(
            symbol=symbol,
            timeframe=timeframe,
            setup_type=SetupType.COMPRESSION,
            direction=direction,
            detected_at=current.open_time,
            current_price=current.close,
            metadata={"range_ratio": str(range_ratio)},
            candle_timestamp=current.open_time,
        )
