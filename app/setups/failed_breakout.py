"""FAILED_BREAKOUT detector — identifies false breakouts that reverse."""

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

FAILURE_WINDOW_BARS = 6


class FailedBreakoutDetector(BaseSetupDetector):
    """Detect failed breakouts (false breakouts that reverse)."""

    @property
    def setup_type(self) -> SetupType:
        return SetupType.FAILED_BREAKOUT

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

        if phase == "IDLE":
            return self._check_initial_breakout(symbol, timeframe, candles, indicators, state)
        if phase == "WATCHING_FAILURE":
            return self._check_failure_return(symbol, timeframe, candles, indicators, state)
        return None

    def _check_initial_breakout(
        self, symbol: str, timeframe: str, candles: list[CandleData],
        indicators: IndicatorSnapshot, state: dict[str, Any],
    ) -> SetupSignal | None:
        if len(candles) < 21:
            return None

        current = candles[-1]
        history = candles[-21:-1]
        resistance = max(c.high for c in history)
        support = min(c.low for c in history)

        if current.close > resistance:
            state["phase"] = "WATCHING_FAILURE"
            state["failure_type"] = "FAILED_UP"
            state["level"] = str(resistance)
            state["trigger_time"] = current.open_time.isoformat()
            state["bars_since_trigger"] = 0
            return None

        if current.close < support:
            state["phase"] = "WATCHING_FAILURE"
            state["failure_type"] = "FAILED_DOWN"
            state["level"] = str(support)
            state["trigger_time"] = current.open_time.isoformat()
            state["bars_since_trigger"] = 0
            return None

        return None

    def _check_failure_return(
        self, symbol: str, timeframe: str, candles: list[CandleData],
        indicators: IndicatorSnapshot, state: dict[str, Any],
    ) -> SetupSignal | None:
        level = Decimal(str(state["level"]))
        failure_type = state["failure_type"]
        bars_since = int(state.get("bars_since_trigger", 0)) + 1
        state["bars_since_trigger"] = bars_since

        if bars_since > FAILURE_WINDOW_BARS:
            state["phase"] = "IDLE"
            return None

        if len(candles) < 1:
            return None

        current = candles[-1]
        ema20 = indicators.ema20
        ema50 = indicators.ema50

        if failure_type == "FAILED_UP":
            if current.close < level:
                confirmed = False
                if ema20 is not None and current.close < ema20:
                    confirmed = True
                if ema50 is not None and current.close < ema50:
                    confirmed = True
                if confirmed:
                    signal = SetupSignal(
                        symbol=symbol,
                        timeframe=timeframe,
                        setup_type=SetupType.FAILED_BREAKOUT,
                        direction=Direction.SHORT,
                        detected_at=current.open_time,
                        current_price=current.close,
                        metadata={"failed_level": str(level), "bars_since_trigger": bars_since},
                        candle_timestamp=current.open_time,
                    )
                    state["phase"] = "IDLE"
                    return signal

        elif failure_type == "FAILED_DOWN":
            if current.close > level:
                confirmed = False
                if ema20 is not None and current.close > ema20:
                    confirmed = True
                if ema50 is not None and current.close > ema50:
                    confirmed = True
                if confirmed:
                    signal = SetupSignal(
                        symbol=symbol,
                        timeframe=timeframe,
                        setup_type=SetupType.FAILED_BREAKOUT,
                        direction=Direction.LONG,
                        detected_at=current.open_time,
                        current_price=current.close,
                        metadata={"failed_level": str(level), "bars_since_trigger": bars_since},
                        candle_timestamp=current.open_time,
                    )
                    state["phase"] = "IDLE"
                    return signal

        return None
