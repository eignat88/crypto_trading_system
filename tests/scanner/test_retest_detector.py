"""Tests for RETEST_READY detector."""

from datetime import datetime, timedelta, UTC
from decimal import Decimal

from app.setups.base import Direction, SetupType
from app.setups.breakout_retest import RetestReadyDetector


class TestRetestReadyDetector:
    def setup_method(self):
        self.detector = RetestReadyDetector()
        self.symbol = "BTCUSDT"
        self.timeframe = "1h"

    def test_no_signal_idle_state(self, make_candle, make_indicators):
        candles = [make_candle() for _ in range(5)]
        indicators = make_indicators()
        state = {"phase": "IDLE"}
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators, state)
        assert result is None

    def test_long_retest_success(self, make_candle, make_indicators, base_time):
        state = {
            "phase": "WAITING_RETEST",
            "breakout_level": "100.0",
            "breakout_time": base_time.isoformat(),
            "direction": "LONG",
            "bars_since_breakout": 2,
        }
        candles = [make_candle(
            open_time=base_time + timedelta(hours=5),
            low=99.5,
            close=102.0,
        )]
        indicators = make_indicators(ema50=100.0, ema200=90.0, atr=2.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators, state)
        assert result is not None
        assert result.setup_type == SetupType.RETEST_READY
        assert result.direction == Direction.LONG
        assert state["phase"] == "IDLE"

    def test_timeout_resets_state(self, make_candle, make_indicators, base_time):
        state = {
            "phase": "WAITING_RETEST",
            "breakout_level": "100.0",
            "breakout_time": base_time.isoformat(),
            "direction": "LONG",
            "bars_since_breakout": 23,
        }
        candles = [make_candle(
            open_time=base_time + timedelta(hours=30),
            low=99.0,
            close=102.0,
        )]
        indicators = make_indicators(ema50=100.0, ema200=90.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators, state)
        assert result is None
        assert state["phase"] == "IDLE"
