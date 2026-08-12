import math
from decimal import Decimal

from app.indicators.atr import (
    calculate_atr,
    calculate_atr_percentage,
    calculate_atr_series,
)
from app.indicators.ema import calculate_ema, calculate_ema_series
from app.indicators.price import (
    calculate_distance_to_ema,
    calculate_high_low_range,
    calculate_price_change,
)
from app.indicators.rsi import calculate_rsi, calculate_rsi_series
from app.indicators.volatility import (
    calculate_historical_volatility,
    calculate_historical_volatility_series,
    calculate_volatility_regime,
)
from app.indicators.volume import (
    calculate_average_volume,
    calculate_volume_ratio,
    calculate_volume_trend,
)


class TestEMA:
    def test_ema_basic(self):
        prices = [Decimal(str(i)) for i in range(1, 21)]
        result = calculate_ema(prices, 10)
        assert result is not None
        assert result > 0

    def test_ema_reference_values(self):
        prices = [Decimal(str(i)) for i in range(1, 7)]
        assert calculate_ema_series(prices, 3) == [
            None,
            None,
            Decimal("2"),
            Decimal("3"),
            Decimal("4"),
            Decimal("5"),
        ]

    def test_ema_insufficient_data(self):
        prices = [Decimal(str(i)) for i in range(1, 5)]
        result = calculate_ema(prices, 10)
        assert result is None

    def test_ema_series(self):
        prices = [Decimal(str(i)) for i in range(1, 21)]
        result = calculate_ema_series(prices, 10)
        assert len(result) == 20
        assert result[8] is None
        assert result[9] is not None

    def test_ema_incremental(self):
        prices = [Decimal(str(i)) for i in range(1, 11)]
        ema1 = calculate_ema(prices, 5)
        ema2 = calculate_ema(prices + [Decimal("11")], 5, previous_ema=ema1)
        assert ema2 is not None
        assert ema2 > ema1

    def test_ema_series_is_causal(self):
        prices = [Decimal(str(100 + i * i)) for i in range(30)]
        full = calculate_ema_series(prices, 5)
        for index in (4, 10, 20, 29):
            prefix = calculate_ema_series(prices[: index + 1], 5)
            assert full[index] == prefix[-1]


class TestRSI:
    def test_rsi_basic(self):
        prices = [Decimal(str(100 + i)) for i in range(20)]
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert result > 50

    def test_rsi_reference_value(self):
        prices = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("1")]
        assert calculate_rsi(prices, 3) == Decimal("50")

    def test_rsi_flat_series_is_neutral(self):
        prices = [Decimal("100")] * 20
        assert calculate_rsi(prices, 14) == Decimal("50")
        series = calculate_rsi_series(prices, 14)
        assert series[14:] == [Decimal("50")] * 6

    def test_rsi_downtrend(self):
        prices = [Decimal(str(100 - i)) for i in range(20)]
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert result < 50

    def test_rsi_insufficient_data(self):
        prices = [Decimal(str(i)) for i in range(5)]
        result = calculate_rsi(prices, 14)
        assert result is None

    def test_rsi_series_is_causal(self):
        prices = [Decimal(str(100 + ((i % 5) - 2) * 3 + i)) for i in range(40)]
        full = calculate_rsi_series(prices, 14)
        for index in (14, 20, 30, 39):
            assert full[index] == calculate_rsi(prices[: index + 1], 14)


class TestATR:
    def test_atr_basic(self):
        highs = [Decimal(str(100 + i * 2)) for i in range(20)]
        lows = [Decimal(str(90 + i * 2)) for i in range(20)]
        closes = [Decimal(str(95 + i * 2)) for i in range(20)]
        result = calculate_atr(highs, lows, closes, 14)
        assert result is not None
        assert result > 0

    def test_atr_reference_value(self):
        highs = [Decimal("2"), Decimal("3"), Decimal("4"), Decimal("3")]
        lows = [Decimal("0"), Decimal("1"), Decimal("2"), Decimal("1")]
        closes = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("2")]
        assert calculate_atr(highs, lows, closes, 3) == Decimal("2")

    def test_atr_percentage(self):
        atr = Decimal("5")
        price = Decimal("100")
        result = calculate_atr_percentage(atr, price)
        assert result == Decimal("0.05")

    def test_atr_series_is_causal(self):
        closes = [Decimal(str(100 + i + (i % 3))) for i in range(30)]
        highs = [value + Decimal("2") for value in closes]
        lows = [value - Decimal("2") for value in closes]
        full = calculate_atr_series(highs, lows, closes, 5)
        for index in (5, 10, 20, 29):
            expected = calculate_atr(
                highs[: index + 1],
                lows[: index + 1],
                closes[: index + 1],
                5,
            )
            assert full[index] == expected


class TestVolatility:
    @staticmethod
    def _varying_closes() -> list[Decimal]:
        percentage_changes = [
            Decimal("0.01"),
            Decimal("-0.02"),
            Decimal("0.03"),
            Decimal("-0.01"),
        ]
        closes = [Decimal("100")]
        for i in range(1, 30):
            change = percentage_changes[(i - 1) % len(percentage_changes)]
            closes.append(closes[-1] * (Decimal("1") + change))
        return closes

    def test_historical_volatility(self):
        result = calculate_historical_volatility(self._varying_closes(), 20)
        assert result is not None
        assert result > 0

    def test_hourly_annualization_factor(self):
        closes = self._varying_closes()
        raw = calculate_historical_volatility(
            closes, 20, annualize=False, timeframe="1h"
        )
        annualized = calculate_historical_volatility(
            closes, 20, annualize=True, timeframe="1h"
        )
        assert raw is not None and raw > 0
        assert annualized is not None
        expected = Decimal(str(math.sqrt(365 * 24)))
        assert abs((annualized / raw) - expected) < Decimal("1e-12")

    def test_daily_annualization_factor(self):
        closes = self._varying_closes()
        raw = calculate_historical_volatility(
            closes, 20, annualize=False, timeframe="1d"
        )
        annualized = calculate_historical_volatility(
            closes, 20, annualize=True, timeframe="1d"
        )
        assert raw is not None and raw > 0
        assert annualized is not None
        expected = Decimal(str(math.sqrt(365)))
        assert abs((annualized / raw) - expected) < Decimal("1e-12")

    def test_historical_volatility_with_constant_returns(self):
        constant_return_closes = [Decimal("100")]
        for _ in range(1, 30):
            constant_return_closes.append(constant_return_closes[-1] * Decimal("1.01"))

        for annualize in (True, False):
            result = calculate_historical_volatility(
                constant_return_closes,
                20,
                annualize=annualize,
                timeframe="1h",
            )
            assert result == Decimal("0")

    def test_volatility_series_is_causal(self):
        closes = self._varying_closes()
        full = calculate_historical_volatility_series(
            closes, 5, timeframe="1h"
        )
        for index in (5, 10, 20, 29):
            expected = calculate_historical_volatility(
                closes[: index + 1],
                5,
                timeframe="1h",
            )
            assert full[index] == expected

    def test_volatility_regime(self):
        assert calculate_volatility_regime(Decimal("0.2")) == "LOW"
        assert calculate_volatility_regime(Decimal("0.5")) == "NORMAL"
        assert calculate_volatility_regime(Decimal("1.0")) == "HIGH"


class TestVolume:
    def test_average_volume(self):
        volumes = [Decimal(str(i * 100)) for i in range(1, 21)]
        result = calculate_average_volume(volumes, 10)
        assert result is not None
        assert result == Decimal("1550")

    def test_volume_ratio(self):
        current = Decimal("1500")
        average = Decimal("1000")
        result = calculate_volume_ratio(current, average)
        assert result == Decimal("1.5")

    def test_volume_trend(self):
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
