"""RETEST_READY detector — identifies price returning to test a breakout level."""

from __future__ import annotations

from datetime import datetime
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

RETEST_TIMEOUT_BARS = 24
RETEST_TOLERANCE_ATR_FACTOR = Decimal("0.25")


class RetestReadyDetector(BaseSetupDetector):
    """Detect when price returns to test a breakout level."""

    @property
    def setup_type(self) -> SetupType:
        return SetupType.RETEST_READY

    def detect(
        self,
        symbol: str,
        timeframe: str,
        candles: list[CandleData],
        indicators: IndicatorSnapshot,
        state: dict[str, Any] | None = None,
    ) -> SetupSignal | None:
        if state is None:
            return None

        phase = state.get("phase", "IDLE")
        if phase != "WAITING_RETEST":
            return None

        breakout_level = state.get("breakout_level")
        if breakout_level is None:
            return None
        breakout_level = Decimal(str(breakout_level))

        direction_str = state.get("direction", "LONG")
        bars_since_breakout = int(state.get("bars_since_breakout", 0))

        # Increment counter first, then check timeout
        state["bars_since_breakout"] = bars_since_breakout + 1

        if state["bars_since_breakout"] >= RETEST_TIMEOUT_BARS:
            state["phase"] = "IDLE"
            return None

        if len(candles) < 1:
            return None

        current = candles[-1]
        ema50 = indicators.ema50
        ema200 = indicators.ema200
        atr = indicators.atr

        if ema50 is None or ema200 is None:
            return None

        tolerance = RETEST_TOLERANCE_ATR_FACTOR * atr if atr is not None else Decimal("0")

        if direction_str == "LONG":
            if current.low <= breakout_level + tolerance and current.close >= breakout_level:
                if ema50 <= ema200:
                    return None
                if current.close <= ema200:
                    return None

                signal = SetupSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    setup_type=SetupType.RETEST_READY,
                    direction=Direction.LONG,
                    detected_at=current.open_time,
                    current_price=current.close,
                    metadata={
                        "breakout_level": str(breakout_level),
                        "bars_since_breakout": state["bars_since_breakout"],
                    },
                    candle_timestamp=current.open_time,
                )
                state["phase"] = "IDLE"
                return signal

        elif direction_str == "SHORT":
            if current.high >= breakout_level - tolerance and current.close <= breakout_level:
                if ema50 >= ema200:
                    return None
                if current.close >= ema200:
                    return None

                signal = SetupSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    setup_type=SetupType.RETEST_READY,
                    direction=Direction.SHORT,
                    detected_at=current.open_time,
                    current_price=current.close,
                    metadata={
                        "breakout_level": str(breakout_level),
                        "bars_since_breakout": state["bars_since_breakout"],
                    },
                    candle_timestamp=current.open_time,
                )
                state["phase"] = "IDLE"
                return signal

        return None

    def arm_from_breakout(
        self,
        state: dict[str, Any],
        breakout_level: Decimal,
        breakout_time: datetime,
        direction: str,
    ) -> None:
        """Arm the retest detector from a breakout signal."""
        state["phase"] = "WAITING_RETEST"
        state["breakout_level"] = str(breakout_level)
        state["breakout_time"] = breakout_time.isoformat()
        state["direction"] = direction
        state["bars_since_breakout"] = 0
