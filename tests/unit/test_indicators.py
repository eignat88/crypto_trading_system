import pytest
from decimal import Decimal

from app.indicators.ema import calculate_ema, calculate_ema_series, calculate_ema_slope
from app.indicators.rsi import calculate_rsi, calculate_rsi_series
from app.indicators.atr import calculate_atr, calculate_atr_series, calculate_atr_percentage
from app.indicators.volatility import (
    calculate_historical_volatility,
    calculate_volatility_regime,
    calculate_bollinger_bands,
)
from app.indicators.volume import (
    calculate_average_volume,
    calculate_volume_ratio,
    calculate_volume_trend,
)
from app.indicators.price import (
    calculate_price_change,
    calculate_distance_to_ema,
    calculate_high_low_range,
)


class TestEMA:
    def test_ema_basic(self):
        prices = [Decimal(str(i)) for i in range(1, 21)]
        result = calculate_ema(prices, 10)
        assert result is not None
        assert result > 0

    def test_ema_insufficient_data(self):
        prices = [Decimal(str(i)) for i in range(1, 5)]
        result = calculate_ema(prices, 10)
        assert result is None

    def test_ema_series(self):
        prices = [Decimal(str(i)) for i in range(1, 21)]
        result = calculate_ema_series(prices, 10)
        assert len(result) == 20
        assert result[8] is None  # First 9 values should be None
        assert result[9] is not None  # 10th value should have EMA

    def test_ema_incremental(self):
        prices = [Decimal(str(i)) for i in range(1, 11)]
        ema1 = calculate_ema(prices, 5)
        ema2 = calculate_ema(prices + [Decimal("11")], 5, previous_ema=ema1)
        assert ema2 is not None
        assert ema2 > ema1


class TestRSI:
    def test_rsi_basic(self):
        # Simulate uptrend
        prices = [Decimal(str(100 + i)) for i in range(20)]
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert result > 50  # Should be bullish

    def test_rsi_downtrend(self):
        # Simulate downtrend
        prices = [Decimal(str(100 - i)) for i in range(20)]
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert result < 50  # Should be bearish

    def test_rsi_insufficient_data(self):
        prices = [Decimal(str(i)) for i in range(5)]
        result = calculate_rsi(prices, 14)
        assert result is None


class TestATR:
    def test_atr_basic(self):
        highs = [Decimal(str(100 + i * 2)) for i in range(20)]
        lows = [Decimal(str(90 + i * 2)) for i in range(20)]
        closes = [Decimal(str(95 + i * 2)) for i in range(20)]
        result = calculate_atr(highs, lows, closes, 14)
        assert result is not None
        assert result > 0

    def test_atr_percentage(self):
        atr = Decimal("5")
        price = Decimal("100")
        result = calculate_atr_percentage(atr, price)
        assert result == Decimal("0.05")


class TestVolatility:
    def test_historical_volatility(self):
        # Create some price data with volatility
        closes = [Decimal("100")]
        for i in range(1, 30):
            closes.append(closes[-1] * Decimal("1.01"))
        result = calculate_historical_volatility(closes, 20)
        assert result is not None
        assert result > 0

    def test_volatility_regime(self):
        assert calculate_volatility_regime(Decimal("0.2")) == "LOW"
        assert calculate_volatility_regime(Decimal("0.5")) == "NORMAL"
        assert calculate_volatility_regime(Decimal("1.0")) == "HIGH"


class TestVolume:
    def test_average_volume(self):
        volumes = [Decimal(str(i * 100)) for i in range(1, 21)]
        result = calculate_average_volume(volumes, 10)
        assert result is not None
        assert result == Decimal("1550")  # Average of 1100-2000

    def test_volume_ratio(self):
        current = Decimal("1500")
        average = Decimal("1000")
        result = calculate_volume_ratio(current, average)
        assert result == Decimal("1.5")

    def test_volume_trend(self):
        # Increasing volume
        volumes = [Decimal("100")] * 15 + [Decimal("200")] * 5
        result = calculate_volume_trend(volumes, 5, 20)
        assert result == "INCREASING"


class TestPrice:
    def test_price_change(self):
        current = Decimal("105")
        previous = Decimal("100")
        result = calculate_price_change(current, previous)
        assert result == Decimal("0.05")

    def test_distance_to_ema(self):
        price = Decimal("105")
        ema = Decimal("100")
        result = calculate_distance_to_ema(price, ema)
        assert result == Decimal("0.05")

    def test_high_low_range(self):
        high = Decimal("110")
        low = Decimal("100")
        result = calculate_high_low_range(high, low)
        assert result == Decimal("0.10")
