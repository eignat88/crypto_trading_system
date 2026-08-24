"""BREAKOUT detector — identifies price breaking above/below significant levels."""

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

RESISTANCE_LOOKBACK = 20


class BreakoutDetector(BaseSetupDetector):
    """Detect breakout above resistance or below support."""

    @property
    def setup_type(self) -> SetupType:
        return SetupType.BREAKOUT

    def detect(
        self,
        symbol: str,
        timeframe: str,
        candles: list[CandleData],
        indicators: IndicatorSnapshot,
        state: dict[str, Any] | None = None,
    ) -> SetupSignal | None:
        if len(candles) < RESISTANCE_LOOKBACK + 1:
            return None

        current = candles[-1]
        history = candles[-(RESISTANCE_LOOKBACK + 1):-1]

        resistance = max(c.high for c in history)
        support = min(c.low for c in history)

        ema50 = indicators.ema50
        ema200 = indicators.ema200

        if ema50 is None or ema200 is None:
            return None

        # LONG breakout
        if current.close > resistance:
            if ema50 <= ema200:
                return None
            if current.close <= ema200:
                return None
            return SetupSignal(
                symbol=symbol,
                timeframe=timeframe,
                setup_type=SetupType.BREAKOUT,
                direction=Direction.LONG,
                detected_at=current.open_time,
                current_price=current.close,
                metadata={"breakout_level": str(resistance)},
                candle_timestamp=current.open_time,
            )

        # SHORT breakout
        if current.close < support:
            if ema50 >= ema200:
                return None
            if current.close >= ema200:
                return None
            return SetupSignal(
                symbol=symbol,
                timeframe=timeframe,
                setup_type=SetupType.BREAKOUT,
                direction=Direction.SHORT,
                detected_at=current.open_time,
                current_price=current.close,
                metadata={"breakout_level": str(support)},
                candle_timestamp=current.open_time,
            )

        return None
