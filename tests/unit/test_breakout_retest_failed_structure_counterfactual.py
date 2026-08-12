from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_failed_structure_counterfactual import (
    build_failed_structure_counterfactual,
    evaluate_failed_structure_trade,
)

UTC = timezone.utc


def _trade(**changes) -> BreakoutRetestTrade:
    base = BreakoutRetestTrade(
        symbol="BTCUSDT",
        window_index=1,
        breakout_time=datetime(2026, 1, 1, 0, tzinfo=UTC),
        breakout_level=Decimal("100"),
        breakout_close=Decimal("102"),
        breakout_strength_pct=Decimal("0.02"),
        retest_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
        bars_to_retest=1,
        retest_low=Decimal("99"),
        retest_close=Decimal("101"),
        retest_depth_pct=Decimal("0.01"),
        retest_close_offset_pct=Decimal("0.01"),
        entry_fill_time=datetime(2026, 1, 1, 2, tzinfo=UTC),
        entry_price=Decimal("101"),
        quantity=Decimal("1"),
        entry_regime="TREND_UP",
        entry_ema50=Decimal("99"),
        entry_ema200=Decimal("90"),
        entry_volatility=Decimal("0.1"),
        exit_time=datetime(2026, 1, 5, 10, tzinfo=UTC),
        exit_price=Decimal("95"),
        exit_reason="Regime changed to TREND_DOWN",
        entry_commission=Decimal("0.101"),
        exit_commission=Decimal("0.095"),
        realized_pnl=Decimal("-6.196"),
        holding_bars=104,
    )
    return replace(base, **changes)


def _candles(
    trade: BreakoutRetestTrade,
    *,
    snapshot_close: Decimal = Decimal("98"),
    ema20: Decimal = Decimal("99"),
    ema50: Decimal = Decimal("100"),
    execution_open: Decimal = Decimal("97"),
) -> list[dict]:
    rows = []
    start = trade.entry_fill_time
    for i in range(30):
        ts = start + timedelta(hours=i)
        close = Decimal("101")
        indicators = {"ema_20": Decimal("100"), "ema_50": Decimal("99")}
        open_price = close
        if i == 23:
            close = snapshot_close
            indicators = {"ema_20": ema20, "ema_50": ema50}
        if i == 24:
            open_price = execution_open
            close = execution_open
        rows.append(
            {
                "open_time": ts,
                "open": open_price,
                "high": max(open_price, close),
                "low": min(open_price, close),
                "close": close,
                "indicators": indicators,
            }
        )
    return rows


def test_uses_24th_completed_bar_and_next_open() -> None:
    trade = _trade()
    result = evaluate_failed_structure_trade(trade, candles=_candles(trade))
    assert result.snapshot_time == trade.entry_fill_time + timedelta(hours=23)
    assert result.hypothetical_exit_time == trade.entry_fill_time + timedelta(hours=24)
    assert result.hypothetical_reference_price == Decimal("97")
    assert result.triggered is True


def test_requires_all_three_strict_structure_conditions() -> None:
    trade = _trade()
    assert evaluate_failed_structure_trade(
        trade, candles=_candles(trade, snapshot_close=Decimal("100"), ema20=Decimal("99"), ema50=Decimal("101"))
    ).triggered is False  # not below EMA20
    assert evaluate_failed_structure_trade(
        trade, candles=_candles(trade, snapshot_close=Decimal("99"), ema20=Decimal("100"), ema50=Decimal("98"))
    ).triggered is False  # not below EMA50
    assert evaluate_failed_structure_trade(
        trade, candles=_candles(trade, snapshot_close=Decimal("100"), ema20=Decimal("101"), ema50=Decimal("102"))
    ).triggered is False  # equal breakout level is not strictly below


def test_missing_ema_fails_closed() -> None:
    trade = _trade()
    candles = _candles(trade)
    candles[23]["indicators"]["ema_20"] = None
    with pytest.raises(ValueError, match="Missing EMA20/EMA50"):
        evaluate_failed_structure_trade(trade, candles=candles)


def test_actual_exit_on_or_before_execution_is_not_rewritten() -> None:
    trade = _trade(exit_time=datetime(2026, 1, 2, 2, tzinfo=UTC))
    result = evaluate_failed_structure_trade(trade, candles=_candles(trade))
    assert result.triggered is False
    assert result.counterfactual_pnl == trade.realized_pnl


def test_triggered_sell_has_costs_and_is_deterministic() -> None:
    trade = _trade()
    one = evaluate_failed_structure_trade(trade, candles=_candles(trade), base_seed=42)
    two = evaluate_failed_structure_trade(trade, candles=_candles(trade), base_seed=42)
    assert one.hypothetical_execution_price == two.hypothetical_execution_price
    assert one.hypothetical_exit_commission == two.hypothetical_exit_commission
    assert one.hypothetical_execution_price is not None
    assert one.hypothetical_execution_price < Decimal("97")
    assert one.hypothetical_exit_commission is not None
    assert one.hypothetical_exit_commission > 0


def test_sacrificed_winner_and_saved_loser_labels() -> None:
    loser = _trade()
    loser_result = evaluate_failed_structure_trade(loser, candles=_candles(loser))
    assert loser_result.saved_loser is True

    winner = _trade(
        realized_pnl=Decimal("4"),
        exit_price=Decimal("105"),
        exit_reason="Trailing stop hit",
    )
    winner_result = evaluate_failed_structure_trade(winner, candles=_candles(winner))
    assert winner_result.sacrificed_winner is True


def test_hourly_gap_fails_closed() -> None:
    trade = _trade()
    candles = _candles(trade)
    del candles[5]
    with pytest.raises(ValueError, match="Hourly candle gap"):
        evaluate_failed_structure_trade(trade, candles=candles)


def test_summary_window_metrics_and_leave_one_out() -> None:
    first = _trade(window_index=1)
    second = _trade(
        window_index=2,
        entry_fill_time=datetime(2026, 2, 1, 2, tzinfo=UTC),
        breakout_time=datetime(2026, 2, 1, 0, tzinfo=UTC),
        retest_time=datetime(2026, 2, 1, 1, tzinfo=UTC),
        exit_time=datetime(2026, 2, 5, 10, tzinfo=UTC),
    )
    summary = build_failed_structure_counterfactual(
        (first, second),
        candles_by_window={1: _candles(first), 2: _candles(second)},
        symbol="BTCUSDT",
        base_seed=42,
    )
    assert summary.trades == 2
    assert summary.triggered == 2
    assert len(summary.by_window) == 2
    total_window_delta = sum((item["pnl_delta"] for item in summary.by_window), Decimal("0"))
    assert total_window_delta == summary.pnl_delta
    assert summary.leave_one_window_out_min_delta == min(
        summary.pnl_delta - item["pnl_delta"] for item in summary.by_window
    )
