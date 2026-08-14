from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_early_failure_snapshot import (
    build_24h_snapshot,
    build_snapshot_stats,
    categorical_counts,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _trade(
    *,
    pnl: Decimal = Decimal("1"),
    exit_reason: str = "Trailing stop hit",
    exit_hours: int = 30,
) -> BreakoutRetestTrade:
    return BreakoutRetestTrade(
        symbol="BTCUSDT",
        window_index=1,
        breakout_time=T0 - timedelta(hours=2),
        breakout_level=Decimal("99"),
        breakout_close=Decimal("101"),
        breakout_strength_pct=Decimal("2") / Decimal("99"),
        retest_time=T0 - timedelta(hours=1),
        bars_to_retest=1,
        retest_low=Decimal("98.5"),
        retest_close=Decimal("100"),
        retest_depth_pct=Decimal("0.5") / Decimal("99"),
        retest_close_offset_pct=Decimal("1") / Decimal("99"),
        entry_fill_time=T0,
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        entry_regime="TREND_UP",
        entry_ema50=Decimal("99"),
        entry_ema200=Decimal("95"),
        entry_volatility=Decimal("0.1"),
        exit_time=T0 + timedelta(hours=exit_hours),
        exit_price=Decimal("101"),
        exit_reason=exit_reason,
        entry_commission=Decimal("0.1"),
        exit_commission=Decimal("0.1"),
        realized_pnl=pnl,
        holding_bars=exit_hours,
    )


def _candles(*, future_extreme: bool = False) -> list[dict]:
    candles = []
    for hour in range(31):
        close = Decimal("100") + Decimal(hour) / Decimal("10")
        regime = "TREND_UP"
        if hour in (10, 11):
            regime = "RANGE"
        if hour >= 12:
            regime = "TREND_UP"
        high = close + Decimal("1")
        low = close - Decimal("1")
        if hour == 5:
            high = Decimal("106")
        if hour == 7:
            low = Decimal("96")
        if future_extreme and hour == 24:
            high = Decimal("150")
            low = Decimal("50")
        candles.append(
            {
                "symbol": "BTCUSDT",
                "open_time": T0 + timedelta(hours=hour),
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "indicators": {
                    "ema_20": Decimal("99") + Decimal(hour) / Decimal("20"),
                    "ema_50": Decimal("98") + Decimal(hour) / Decimal("40"),
                    "ema_200": Decimal("95") + Decimal(hour) / Decimal("100"),
                    "atr": Decimal("2"),
                    "volatility": Decimal("0.12"),
                    "regime": regime,
                    "regime_confidence": Decimal("0.8"),
                },
            }
        )
    return candles


def test_snapshot_uses_exact_24_completed_hourly_candles() -> None:
    snapshot = build_24h_snapshot(_trade(), _candles())
    assert snapshot is not None
    assert snapshot.snapshot_time == T0 + timedelta(hours=23)
    assert snapshot.close_24h == Decimal("102.3")
    assert snapshot.return_24h_pct == Decimal("0.023")


def test_trade_closed_on_24h_snapshot_candle_is_not_eligible() -> None:
    assert build_24h_snapshot(_trade(exit_hours=23), _candles()) is None


def test_future_candle_extremes_do_not_change_24h_mfe_or_mae() -> None:
    normal = build_24h_snapshot(_trade(), _candles())
    extreme = build_24h_snapshot(_trade(), _candles(future_extreme=True))
    assert normal is not None and extreme is not None
    assert normal.mfe_24h_pct == extreme.mfe_24h_pct == Decimal("0.06")
    assert normal.mae_24h_pct == extreme.mae_24h_pct == Decimal("-0.04")


def test_ema_distance_and_one_bar_slope_are_causal() -> None:
    snapshot = build_24h_snapshot(_trade(), _candles())
    assert snapshot is not None
    ema20 = Decimal("99") + Decimal("23") / Decimal("20")
    previous = Decimal("99") + Decimal("22") / Decimal("20")
    assert snapshot.distance_to_ema20_pct == (Decimal("102.3") - ema20) / ema20
    assert snapshot.ema20_slope_1bar_pct == (ema20 - previous) / previous
    assert snapshot.atr_to_close_pct == Decimal("2") / Decimal("102.3")


def test_regime_transitions_are_counted_only_before_snapshot() -> None:
    snapshot = build_24h_snapshot(_trade(), _candles())
    assert snapshot is not None
    assert snapshot.regime_24h == "TREND_UP"
    assert snapshot.regime_transition_count == 2
    assert snapshot.regime_changed_since_entry is False


def test_future_outcome_maps_to_predeclared_groups() -> None:
    winner = build_24h_snapshot(_trade(pnl=Decimal("1")), _candles())
    td = build_24h_snapshot(
        _trade(pnl=Decimal("-1"), exit_reason="Regime changed to TREND_DOWN"),
        _candles(),
    )
    max_hold = build_24h_snapshot(
        _trade(pnl=Decimal("-1"), exit_reason="Max holding period reached"),
        _candles(),
    )
    assert winner is not None and winner.group == "FUTURE_WINNER"
    assert td is not None and td.group == "TREND_DOWN_LOSS"
    assert max_hold is not None and max_hold.group == "MAX_HOLDING_LOSS"


def test_gap_in_hourly_data_fails_closed() -> None:
    candles = _candles()
    del candles[12]
    with pytest.raises(ValueError, match="gapless 1h candles"):
        build_24h_snapshot(_trade(), candles)


def test_stats_and_regime_counts_are_descriptive_only() -> None:
    snapshots = tuple(
        item
        for item in (
            build_24h_snapshot(_trade(pnl=Decimal("1")), _candles()),
            build_24h_snapshot(
                _trade(pnl=Decimal("-1"), exit_reason="Regime changed to TREND_DOWN"),
                _candles(),
            ),
        )
        if item is not None
    )
    stats = build_snapshot_stats(snapshots)
    winner_return = next(
        item for item in stats
        if item.feature == "return_24h_pct" and item.group == "FUTURE_WINNER"
    )
    assert winner_return.count == 1
    assert winner_return.mean == Decimal("0.023")
    assert categorical_counts(snapshots, group="FUTURE_WINNER") == {"TREND_UP": 1}
