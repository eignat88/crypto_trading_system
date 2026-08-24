"""Tests for COMPRESSION detector."""

from datetime import timedelta
from decimal import Decimal

from app.setups.base import Direction, SetupType
from app.setups.compression import CompressionDetector


class TestCompressionDetector:
    def setup_method(self):
        self.detector = CompressionDetector()
        self.symbol = "BTCUSDT"
        self.timeframe = "1h"

    def test_no_signal_insufficient_data(self, make_candle, make_indicators):
        candles = [make_candle() for _ in range(40)]
        indicators = make_indicators()
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators)
        assert result is None

    def test_compression_detected_near_high(self, make_candle, make_indicators, base_time):
        """Compression detected when price near high with higher ATR for tolerance."""
        candles = []
        for i in range(50):
            candles.append(make_candle(
                open_time=base_time + timedelta(hours=i),
                low=100.0,
                high=120.0,
                close=110.0,
            ))
        for i in range(10):
            candles.append(make_candle(
                open_time=base_time + timedelta(hours=50 + i),
                low=115.0,
                high=118.0,
                close=117.0,
            ))
        # Higher ATR so tolerance (0.25 * ATR) covers distance to high (3.0)
        indicators = make_indicators(atr=12.0)
        result = self.detector.detect(self.symbol, self.timeframe, candles, indicators)
        assert result is not None
        assert result.setup_type == SetupType.COMPRESSION
        assert result.direction == Direction.LONG_CANDIDATE
