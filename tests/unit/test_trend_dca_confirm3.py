from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal

from app.indicators.market_regime import MarketRegime
from app.strategies.trend_dca import DCAConfig
from app.strategies.trend_dca_confirm3 import (
    EXPERIMENT_PARAMETERS_VERSION,
    TrendDCAConfirm3Strategy,
)


UTC = timezone.utc


def _candle() -> dict:
    return {
        "symbol": "BTCUSDT",
        "open_time": datetime(2026, 1, 1, tzinfo=UTC),
        "open": Decimal("100"),
        "high": Decimal("100"),
        "low": Decimal("100"),
        "close": Decimal("100"),
    }


def _position() -> dict:
    return {
        "entry_price": Decimal("100"),
        "quantity": Decimal("1"),
        "unrealized_pnl_pct": Decimal("0"),
        "holding_periods": 1,
    }


def _indicators(regime: MarketRegime) -> dict:
    return {"regime": regime}


def test_confirm3_does_not_exit_on_first_two_trend_down_bars():
    strategy = TrendDCAConfirm3Strategy(symbols=["BTCUSDT"])

    first = strategy.should_exit(
        _candle(), _indicators(MarketRegime.TREND_DOWN), _position()
    )
    second = strategy.should_exit(
        _candle(), _indicators(MarketRegime.TREND_DOWN), _position()
    )

    assert first is None
    assert second is None
    assert strategy.trend_down_streaks["BTCUSDT"] == 2


def test_confirm3_exits_on_third_consecutive_trend_down_bar():
    strategy = TrendDCAConfirm3Strategy(symbols=["BTCUSDT"])

    for _ in range(2):
        assert strategy.should_exit(
            _candle(), _indicators(MarketRegime.TREND_DOWN), _position()
        ) is None

    signal = strategy.should_exit(
        _candle(), _indicators(MarketRegime.TREND_DOWN), _position()
    )

    assert signal is not None
    assert signal.reason == "TREND_DOWN confirmed for 3 consecutive bars"
    assert signal.parameters_version == EXPERIMENT_PARAMETERS_VERSION
    assert signal.metadata["confirmation_bars"] == 3
    assert "BTCUSDT" not in strategy.trend_down_streaks


def test_confirm3_resets_streak_when_trend_down_is_interrupted():
    strategy = TrendDCAConfirm3Strategy(symbols=["BTCUSDT"])

    assert strategy.should_exit(
        _candle(), _indicators(MarketRegime.TREND_DOWN), _position()
    ) is None
    assert strategy.should_exit(
        _candle(), _indicators(MarketRegime.RANGE), _position()
    ) is None

    assert "BTCUSDT" not in strategy.trend_down_streaks

    assert strategy.should_exit(
        _candle(), _indicators(MarketRegime.TREND_DOWN), _position()
    ) is None
    assert strategy.trend_down_streaks["BTCUSDT"] == 1


def test_confirm3_has_explicit_experiment_version():
    strategy = TrendDCAConfirm3Strategy(symbols=["BTCUSDT"])

    assert strategy.config.parameters_version == "trend_dca_v1_trend_down_confirm3"


def test_confirm3_keeps_all_baseline_parameters_except_version():
    baseline = asdict(DCAConfig())
    experiment = asdict(TrendDCAConfirm3Strategy(symbols=["BTCUSDT"]).config)

    baseline.pop("parameters_version")
    experiment.pop("parameters_version")

    assert experiment == baseline
