from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.ema200_slope_p75_walk_forward import (
    _percentile,
    add_ema200_slope_10,
    derive_train_p75_threshold,
)
from app.backtest.walk_forward import WalkForwardWindow
from app.indicators.market_regime import MarketRegime
from app.strategies.trend_dca_ema200_slope_p75 import (
    EXPERIMENT_PARAMETERS_VERSION,
    TrendDCAEMA200SlopeP75Strategy,
)

UTC = UTC


def _candle(hour: int, ema200: str, *, rsi: str = "40", regime=MarketRegime.TREND_UP):
    close = Decimal(ema200) * Decimal("1.02")
    return {
        "symbol": "BTCUSDT",
        "open_time": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "indicators": {
            "ema_20": close * Decimal("0.995"),
            "ema_50": Decimal(ema200) * Decimal("1.01"),
            "ema_200": Decimal(ema200),
            "rsi": Decimal(rsi),
            "atr": Decimal("1"),
            "volatility": Decimal("0.2"),
            "regime": regime,
        },
    }


def test_percentile_uses_linear_interpolation():
    values = [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4")]
    assert _percentile(values, Decimal("0.75")) == Decimal("3.25")


def test_add_ema200_slope_10_uses_current_and_nine_bars_back():
    candles = [_candle(i, str(100 + i)) for i in range(10)]
    enriched = add_ema200_slope_10(candles)
    assert enriched[8]["indicators"]["ema200_slope_10"] is None
    assert enriched[9]["indicators"]["ema200_slope_10"] == (Decimal("109") - Decimal("100")) / Decimal("100")


def test_train_threshold_excludes_test_data():
    candles = [_candle(i, str(100 + i)) for i in range(16)]
    enriched = add_ema200_slope_10(candles)
    start = datetime(2026, 1, 1, tzinfo=UTC)
    window = WalkForwardWindow(
        index=1,
        train_start=start,
        train_end=start + timedelta(hours=13),
        test_start=start + timedelta(hours=13),
        test_end=start + timedelta(hours=16),
    )
    threshold_before, count_before = derive_train_p75_threshold(enriched, window)

    # Make TEST EMA values extreme; TRAIN threshold must remain identical.
    modified = list(enriched)
    for i in range(13, 16):
        copied = dict(modified[i])
        indicators = dict(copied["indicators"])
        indicators["ema200_slope_10"] = Decimal("999")
        copied["indicators"] = indicators
        modified[i] = copied

    threshold_after, count_after = derive_train_p75_threshold(modified, window)
    assert threshold_after == threshold_before
    assert count_after == count_before


def test_strategy_blocks_entry_below_frozen_threshold():
    strategy = TrendDCAEMA200SlopeP75Strategy(
        symbols=["BTCUSDT"], ema200_slope_threshold=Decimal("0.005")
    )
    candle = _candle(10, "100")
    indicators = dict(candle["indicators"])
    indicators["ema200_slope_10"] = Decimal("0.0049")
    assert strategy.should_enter(
        candle, indicators, {"has_position": False, "capital": Decimal("500")}
    ) is None


def test_strategy_allows_baseline_entry_at_or_above_threshold_and_versions_signal():
    strategy = TrendDCAEMA200SlopeP75Strategy(
        symbols=["BTCUSDT"], ema200_slope_threshold=Decimal("0.005")
    )
    candle = _candle(10, "100")
    indicators = dict(candle["indicators"])
    indicators["ema200_slope_10"] = Decimal("0.005")
    signal = strategy.should_enter(
        candle, indicators, {"has_position": False, "capital": Decimal("500")}
    )
    assert signal is not None
    assert signal.parameters_version == EXPERIMENT_PARAMETERS_VERSION
    assert signal.metadata["threshold_source"] == "TRAIN_ENTRY_OPPORTUNITY_P75"
    assert signal.metadata["ema200_slope_threshold"] == "0.005"
