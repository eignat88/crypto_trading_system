from decimal import Decimal

from app.collectors.indicator_batch_collector import _ema_slope_at, classify_regime
from app.indicators.atr import calculate_atr_percentage, calculate_atr_series
from app.indicators.ema import calculate_ema_series, calculate_ema_slope
from app.indicators.market_regime import MarketRegimeDetector
from app.indicators.rsi import calculate_rsi_series
from app.indicators.volatility import (
    calculate_historical_volatility,
    calculate_historical_volatility_series,
)


def _series_data(length: int = 320):
    closes = [Decimal("100")]
    for i in range(1, length):
        factor = Decimal("1.002") if i % 7 else Decimal("0.994")
        closes.append(closes[-1] * factor)
    highs = [value * Decimal("1.004") for value in closes]
    lows = [value * Decimal("0.996") for value in closes]
    return closes, highs, lows


def test_volatility_series_matches_scalar_prefix_calculation():
    closes, _, _ = _series_data(120)
    series = calculate_historical_volatility_series(closes, 20)

    for index in range(len(closes)):
        expected = calculate_historical_volatility(closes[: index + 1], 20)
        assert series[index] == expected


def test_direct_ema_slope_matches_existing_prefix_function():
    closes, _, _ = _series_data()
    ema_200 = calculate_ema_series(closes, 200)

    for index in range(199, len(closes)):
        expected = calculate_ema_slope(ema_200[: index + 1], lookback=10)
        assert _ema_slope_at(ema_200, index, lookback=10) == expected


def test_batch_regime_classification_matches_detector():
    closes, highs, lows = _series_data()
    detector = MarketRegimeDetector()
    ema_20 = calculate_ema_series(closes, 20)
    ema_50 = calculate_ema_series(closes, 50)
    ema_200 = calculate_ema_series(closes, 200)
    atr_14 = calculate_atr_series(highs, lows, closes, 14)
    volatility_20 = calculate_historical_volatility_series(closes, 20)
    rsi_14 = calculate_rsi_series(closes, 14)

    assert rsi_14[-1] is not None

    for index in (199, 208, 250, 319):
        expected = detector.detect(
            closes[: index + 1],
            highs[: index + 1],
            lows[: index + 1],
        )
        atr = atr_14[index]
        actual = classify_regime(
            detector=detector,
            current_price=closes[index],
            ema_20=ema_20[index],
            ema_50=ema_50[index],
            ema_200=ema_200[index],
            ema_200_slope=_ema_slope_at(ema_200, index, lookback=10),
            atr_percentage=(
                calculate_atr_percentage(atr, closes[index]) if atr and closes[index] else None
            ),
            volatility=volatility_20[index],
        )

        assert actual.regime == expected.regime
        assert actual.confidence == expected.confidence
        assert actual.reasons == expected.reasons
        assert actual.ema_20 == expected.ema_20
        assert actual.ema_50 == expected.ema_50
        assert actual.ema_200 == expected.ema_200
        assert actual.atr_percentage == expected.atr_percentage
        assert actual.volatility == expected.volatility
