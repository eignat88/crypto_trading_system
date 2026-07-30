import pytest
from decimal import Decimal

from app.indicators.market_regime import MarketRegimeDetector, MarketRegime


class TestMarketRegimeDetector:
    def setup_method(self):
        self.detector = MarketRegimeDetector()

    def test_trend_up_detection(self):
        # Create uptrend data
        closes = [Decimal("100")]
        for i in range(1, 250):
            closes.append(closes[-1] * Decimal("1.005"))
        
        highs = [c * Decimal("1.01") for c in closes]
        lows = [c * Decimal("0.99") for c in closes]
        
        result = self.detector.detect(closes, highs, lows)
        assert result.regime == MarketRegime.TREND_UP
        assert result.confidence > Decimal("0.5")

    def test_trend_down_detection(self):
        # Create downtrend data
        closes = [Decimal("200")]
        for i in range(1, 250):
            closes.append(closes[-1] * Decimal("0.995"))
        
        highs = [c * Decimal("1.01") for c in closes]
        lows = [c * Decimal("0.99") for c in closes]
        
        result = self.detector.detect(closes, highs, lows)
        assert result.regime == MarketRegime.TREND_DOWN
        assert result.confidence > Decimal("0.5")

    def test_range_detection(self):
        # Create ranging data
        closes = []
        for i in range(250):
            closes.append(Decimal("100") + Decimal(str(5 * (i % 10 - 5))))
        
        highs = [c * Decimal("1.01") for c in closes]
        lows = [c * Decimal("0.99") for c in closes]
        
        result = self.detector.detect(closes, highs, lows)
        assert result.regime == MarketRegime.RANGE

    def test_high_volatility_detection(self):
        # Create high volatility data
        closes = [Decimal("100")]
        for i in range(1, 250):
            if i % 2 == 0:
                closes.append(closes[-1] * Decimal("1.10"))
            else:
                closes.append(closes[-1] * Decimal("0.90"))
        
        highs = [c * Decimal("1.05") for c in closes]
        lows = [c * Decimal("0.95") for c in closes]
        
        result = self.detector.detect(closes, highs, lows)
        assert result.regime == MarketRegime.HIGH_VOLATILITY

    def test_insufficient_data(self):
        closes = [Decimal("100"), Decimal("101"), Decimal("102")]
        highs = [Decimal("101"), Decimal("102"), Decimal("103")]
        lows = [Decimal("99"), Decimal("100"), Decimal("101")]
        
        result = self.detector.detect(closes, highs, lows)
        assert result.regime == MarketRegime.RANGE
        assert result.confidence < Decimal("0.5")
