from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.indicators.market_regime import MarketRegime
from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_exit_path import (
    analyze_exit_path,
    build_exit_path_stats,
)

UTC = UTC
START = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(*, exit_hour: int = 10, exit_price: str = "103", pnl: str = "1", reason: str = "Trailing stop hit") -> BreakoutRetestTrade:
    return BreakoutRetestTrade(
        symbol="BTCUSDT",
        window_index=1,
        breakout_time=START - timedelta(hours=2),
        breakout_level=Decimal("100"),
        breakout_close=Decimal("101"),
        breakout_strength_pct=Decimal("0.01"),
        retest_time=START - timedelta(hours=1),
        bars_to_retest=1,
        retest_low=Decimal("99.5"),
        retest_close=Decimal("100.5"),
        retest_depth_pct=Decimal("0.005"),
        retest_close_offset_pct=Decimal("0.005"),
        entry_fill_time=START,
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        entry_regime="TREND_UP",
        entry_ema50=Decimal("99"),
        entry_ema200=Decimal("95"),
        entry_volatility=Decimal("0.1"),
        exit_time=START + timedelta(hours=exit_hour),
        exit_price=Decimal(exit_price),
        exit_reason=reason,
        entry_commission=Decimal("0.1"),
        exit_commission=Decimal("0.1"),
        realized_pnl=Decimal(pnl),
        holding_bars=exit_hour,
    )


def _candle(hour: int, *, close: str = "101", high: str = "102", low: str = "99", regime=MarketRegime.TREND_UP) -> dict:
    return {
        "symbol": "BTCUSDT",
        "open_time": START + timedelta(hours=hour),
        "open": Decimal("100"),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "indicators": {
            "regime": regime,
            "ema_20": Decimal("100"),
            "ema_50": Decimal("99"),
            "ema_200": Decimal("95"),
        },
    }


def _candles(count: int) -> list[dict]:
    return [_candle(hour) for hour in range(count)]


def test_mfe_mae_exclude_full_exit_candle_ohlc() -> None:
    candles = _candles(11)
    candles[10] = _candle(10, high="150", low="50")
    path = analyze_exit_path(_trade(exit_hour=10, exit_price="103"), candles)
    assert path.mfe_pct == Decimal("0.03")
    assert path.mae_pct == Decimal("-0.01")


def test_terminal_exit_price_can_define_mae() -> None:
    candles = _candles(6)
    path = analyze_exit_path(_trade(exit_hour=5, exit_price="90", pnl="-10"), candles)
    assert path.mae_pct == Decimal("-0.10")
    assert path.bars_to_mae == 6


def test_horizon_snapshot_uses_sixth_bar_close_and_ema_state() -> None:
    candles = _candles(20)
    candles[5] = _candle(5, close="104", high="105", low="100")
    path = analyze_exit_path(_trade(exit_hour=10), candles)
    snapshot = next(item for item in path.horizons if item.horizon_hours == 6)
    assert snapshot.candle_time == START + timedelta(hours=5)
    assert snapshot.return_pct == Decimal("0.04")
    assert snapshot.close_above_ema20 is True
    assert snapshot.close_above_ema50 is True
    assert snapshot.close_above_ema200 is True


def test_horizon_on_or_after_exit_is_omitted() -> None:
    path = analyze_exit_path(_trade(exit_hour=5), _candles(10))
    assert path.horizons == ()


def test_first_trend_down_and_pre_trend_down_mfe_are_causal() -> None:
    candles = _candles(12)
    candles[1] = _candle(1, high="106", low="100", close="104")
    candles[2] = _candle(2, high="105", low="98", close="97", regime=MarketRegime.TREND_DOWN)
    path = analyze_exit_path(_trade(exit_hour=10, pnl="-1", reason="Regime changed to TREND_DOWN"), candles)
    assert path.first_trend_down_time == START + timedelta(hours=2)
    assert path.bars_to_trend_down == 3
    assert path.max_favorable_before_trend_down_pct == Decimal("0.06")
    assert path.return_before_trend_down_pct == Decimal("-0.03")


def test_no_trend_down_keeps_trend_down_metrics_none() -> None:
    path = analyze_exit_path(_trade(), _candles(12))
    assert path.first_trend_down_time is None
    assert path.bars_to_trend_down is None
    assert path.max_favorable_before_trend_down_pct is None
    assert path.return_before_trend_down_pct is None


def test_gapless_hourly_data_is_required() -> None:
    candles = _candles(10)
    del candles[4]
    with pytest.raises(ValueError, match="gapless 1h candles"):
        analyze_exit_path(_trade(exit_hour=8), candles)


def test_stats_keep_predeclared_winner_and_loss_groups_separate() -> None:
    winner = analyze_exit_path(_trade(exit_hour=10, exit_price="105", pnl="1", reason="Trailing stop hit"), _candles(12))
    td_loss = analyze_exit_path(_trade(exit_hour=10, exit_price="95", pnl="-1", reason="Regime changed to TREND_DOWN"), _candles(12))
    max_loss = analyze_exit_path(_trade(exit_hour=10, exit_price="96", pnl="-2", reason="Max holding period reached"), _candles(12))
    stats = build_exit_path_stats((winner, td_loss, max_loss))
    lookup = {(item.feature, item.group): item for item in stats}
    assert lookup[("mfe_pct", "WINNER")].count == 1
    assert lookup[("mfe_pct", "TREND_DOWN_LOSS")].count == 1
    assert lookup[("mfe_pct", "MAX_HOLDING_LOSS")].count == 1
    assert lookup[("mfe_pct", "ALL_LOSERS")].count == 2
