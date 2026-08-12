from decimal import Decimal

from app.indicators.market_regime import MarketRegime, MarketRegimeDetector


class TestMarketRegimeDetector:
    def setup_method(self):
        self.detector = MarketRegimeDetector(
            high_volatility_threshold=Decimal("1.5"),
            slope_threshold=Decimal("0.0001"),
        )

    def test_trend_up_detection(self):
        closes = [Decimal("100")]
        for _ in range(1, 300):
            closes.append(closes[-1] * Decimal("1.003"))

        highs = [c * Decimal("1.005") for c in closes]
        lows = [c * Decimal("0.995") for c in closes]

        result = self.detector.detect(closes, highs, lows, timeframe="1h")
        assert result.regime == MarketRegime.TREND_UP
        assert result.confidence >= Decimal("0.5")

    def test_trend_down_detection(self):
        closes = [Decimal("200")]
        for _ in range(1, 300):
            closes.append(closes[-1] * Decimal("0.997"))

        highs = [c * Decimal("1.005") for c in closes]
        lows = [c * Decimal("0.995") for c in closes]

        result = self.detector.detect(closes, highs, lows, timeframe="1h")
        assert result.regime == MarketRegime.TREND_DOWN
        assert result.confidence >= Decimal("0.5")

    def test_range_detection(self):
        closes = [
            Decimal("100.1") if i % 2 == 0 else Decimal("99.9")
            for i in range(300)
        ]
        highs = [c * Decimal("1.002") for c in closes]
        lows = [c * Decimal("0.998") for c in closes]

        result = self.detector.detect(closes, highs, lows, timeframe="1h")
        assert result.regime == MarketRegime.RANGE

    def test_high_volatility_detection(self):
        closes = [Decimal("100")]
        for i in range(1, 300):
            if i % 2 == 0:
                closes.append(closes[-1] * Decimal("1.15"))
            else:
                closes.append(closes[-1] * Decimal("0.85"))

        highs = [c * Decimal("1.05") for c in closes]
        lows = [c * Decimal("0.95") for c in closes]

        result = self.detector.detect(closes, highs, lows, timeframe="1h")
        assert result.regime == MarketRegime.HIGH_VOLATILITY

    def test_insufficient_ema_data_is_unknown(self):
        closes = [Decimal("100"), Decimal("101"), Decimal("102")]
        highs = [Decimal("101"), Decimal("102"), Decimal("103")]
        lows = [Decimal("99"), Decimal("100"), Decimal("101")]

        result = self.detector.detect(closes, highs, lows, timeframe="1h")
        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == Decimal("0")
        assert "Insufficient data for EMA 200" in result.reasons

    def test_insufficient_ema200_slope_is_unknown(self):
        closes = [Decimal("100")]
        for _ in range(1, 205):
            closes.append(closes[-1] * Decimal("1.001"))

        highs = [c * Decimal("1.002") for c in closes]
        lows = [c * Decimal("0.998") for c in closes]

        result = self.detector.detect(closes, highs, lows, timeframe="1h")
        assert result.ema_200 is not None
        assert result.regime == MarketRegime.UNKNOWN
        assert result.confidence == Decimal("0")
        assert "Insufficient EMA 200 history for slope" in result.reasons
