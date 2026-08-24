"""Tests for FAILED_BREAKOUT detector."""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

from app.setups.base import Direction, SetupType
from app.setups.failed_breakout import FailedBreakoutDetector


class TestFailedBreakoutDetector:
    def setup_method(self):
        self.detector = FailedBreakoutDetector()
        self.symbol = "BTCUSDT"
        self.timeframe = "1h"

    def test_bearish_failed_breakout(self, make_candle, make_indicators, base_time):
        state = {
            "phase": "WATCHING_FAILURE",
            "failure_type": "FAILED_UP",
            "level": "100.0",
            "trigger_time": base_time.isoformat(),
            "bars_since_trigger": 0,
        }
        candles = [make_candle(
            open_time=base_time + timedelta(hours=5),
            close=98.0,
        )]
        indicators = make_indicators(ema20=99.0, ema50=95.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators, state)
        assert result is not None
        assert result.setup_type == SetupType.FAILED_BREAKOUT
        assert result.direction == Direction.SHORT
        assert state["phase"] == "IDLE"

    def test_bullish_failed_breakdown(self, make_candle, make_indicators, base_time):
        state = {
            "phase": "WATCHING_FAILURE",
            "failure_type": "FAILED_DOWN",
            "level": "100.0",
            "trigger_time": base_time.isoformat(),
            "bars_since_trigger": 0,
        }
        candles = [make_candle(
            open_time=base_time + timedelta(hours=5),
            close=102.0,
        )]
        indicators = make_indicators(ema20=101.0, ema50=105.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators, state)
        assert result is not None
        assert result.setup_type == SetupType.FAILED_BREAKOUT
        assert result.direction == Direction.LONG
