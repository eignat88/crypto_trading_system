"""Tests for BREAKOUT detector."""

from datetime import timedelta
from decimal import Decimal

from app.setups.base import Direction, SetupType
from app.setups.breakout import BreakoutDetector


class TestBreakoutDetector:
    def setup_method(self):
        self.detector = BreakoutDetector()
        self.symbol = "BTCUSDT"
        self.timeframe = "1h"

    def test_no_signal_insufficient_history(self, make_candle, make_indicators):
        candles = [make_candle() for _ in range(15)]
        indicators = make_indicators()
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators)
        assert result is None

    def test_long_breakout(self, make_candle, make_indicators, base_time):
        candles = []
        for i in range(25):
            high = 100.0 + (i % 10)
            candles.append(make_candle(
                open_time=base_time + timedelta(hours=i),
                high=high,
                close=high - 1,
            ))
        candles.append(make_candle(
            open_time=base_time + timedelta(hours=25),
            high=115.0,
            close=115.0,
        ))
        indicators = make_indicators(ema50=100.0, ema200=90.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators)
        assert result is not None
        assert result.setup_type == SetupType.BREAKOUT
        assert result.direction == Direction.LONG

    def test_short_breakout(self, make_candle, make_indicators, base_time):
        candles = []
        for i in range(25):
            low = 100.0 + (i % 10)
            candles.append(make_candle(
                open_time=base_time + timedelta(hours=i),
                low=low,
                close=low + 1,
            ))
        candles.append(make_candle(
            open_time=base_time + timedelta(hours=25),
            low=85.0,
            close=85.0,
        ))
        indicators = make_indicators(ema50=90.0, ema200=100.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators)
        assert result is not None
        assert result.setup_type == SetupType.BREAKOUT
        assert result.direction == Direction.SHORT

    def test_no_signal_ema_filter_long(self, make_candle, make_indicators, base_time):
        candles = []
        for i in range(25):
            candles.append(make_candle(
                open_time=base_time + timedelta(hours=i),
                high=100.0,
                close=95.0,
            ))
        candles.append(make_candle(
            open_time=base_time + timedelta(hours=25),
            close=115.0,
        ))
        indicators = make_indicators(ema50=80.0, ema200=90.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators)
        assert result is None
