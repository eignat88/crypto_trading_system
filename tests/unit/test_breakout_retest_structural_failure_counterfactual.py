from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_structural_failure_counterfactual import (
    build_structural_failure_counterfactual,
    evaluate_structural_failure_trade,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(
    *,
    pnl: Decimal = Decimal("-1"),
    exit_reason: str = "Regime changed to TREND_DOWN",
    exit_hours: int = 50,
    breakout_level: Decimal = Decimal("100"),
) -> BreakoutRetestTrade:
    return BreakoutRetestTrade(
        symbol="BTCUSDT",
        window_index=1,
        breakout_time=T0 - timedelta(hours=2),
        breakout_level=breakout_level,
        breakout_close=Decimal("101"),
        breakout_strength_pct=Decimal("0.01"),
        retest_time=T0 - timedelta(hours=1),
        bars_to_retest=1,
        retest_low=Decimal("99"),
        retest_close=Decimal("100"),
        retest_depth_pct=Decimal("0.01"),
        retest_close_offset_pct=Decimal("0"),
        entry_fill_time=T0,
        entry_price=Decimal("100"),
        quantity=Decimal("1"),
        entry_regime="TREND_UP",
        entry_ema50=Decimal("99"),
        entry_ema200=Decimal("95"),
        entry_volatility=Decimal("0.1"),
        exit_time=T0 + timedelta(hours=exit_hours),
        exit_price=Decimal("99"),
        exit_reason=exit_reason,
        entry_commission=Decimal("0.1"),
        exit_commission=Decimal("0.1"),
        realized_pnl=pnl,
        holding_bars=exit_hours,
    )


def _candles(
    *,
    snapshot_close: Decimal = Decimal("99"),
    snapshot_ema20: Decimal = Decimal("100"),
    previous_ema20: Decimal = Decimal("101"),
    execution_open: Decimal = Decimal("98.5"),
) -> list[dict]:
    candles = []
    for hour in range(60):
        close = Decimal("101")
        ema20 = Decimal("100")
        if hour == 22:
            ema20 = previous_ema20
        if hour == 23:
            close = snapshot_close
            ema20 = snapshot_ema20
        open_price = execution_open if hour == 24 else close
        candles.append(
            {
                "symbol": "BTCUSDT",
                "open_time": T0 + timedelta(hours=hour),
                "open": open_price,
                "high": max(open_price, close) + Decimal("1"),
                "low": min(open_price, close) - Decimal("1"),
                "close": close,
                "indicators": {"ema_20": ema20},
            }
        )
    return candles


def test_frozen_three_conditions_trigger_and_execute_on_n_plus_1_open() -> None:
    result = evaluate_structural_failure_trade(_trade(), candles=_candles(), base_seed=42)
    assert result.snapshot_time == T0 + timedelta(hours=23)
    assert result.triggered is True
    assert result.below_breakout_level is True
    assert result.below_ema20 is True
    assert result.ema20_falling is True
    assert result.hypothetical_exit_time == T0 + timedelta(hours=24)
    assert result.hypothetical_reference_price == Decimal("98.5")


def test_close_equal_breakout_level_does_not_trigger() -> None:
    result = evaluate_structural_failure_trade(
        _trade(),
        candles=_candles(snapshot_close=Decimal("100"), snapshot_ema20=Decimal("101")),
    )
    assert result.below_breakout_level is False
    assert result.triggered is False


def test_close_equal_ema20_does_not_trigger() -> None:
    result = evaluate_structural_failure_trade(
        _trade(),
        candles=_candles(snapshot_close=Decimal("99"), snapshot_ema20=Decimal("99")),
    )
    assert result.below_ema20 is False
    assert result.triggered is False


def test_flat_ema20_does_not_trigger() -> None:
    result = evaluate_structural_failure_trade(
        _trade(),
        candles=_candles(snapshot_ema20=Decimal("100"), previous_ema20=Decimal("100")),
    )
    assert result.ema20_falling is False
    assert result.triggered is False


def test_actual_exit_at_n_plus_1_prevents_counterfactual() -> None:
    result = evaluate_structural_failure_trade(
        _trade(exit_hours=24),
        candles=_candles(),
    )
    assert result.triggered is False
    assert result.counterfactual_pnl == result.actual_pnl


def test_counterfactual_cost_is_deterministic() -> None:
    first = evaluate_structural_failure_trade(_trade(), candles=_candles(), base_seed=42)
    second = evaluate_structural_failure_trade(_trade(), candles=_candles(), base_seed=42)
    assert first.hypothetical_execution_price == second.hypothetical_execution_price
    assert first.hypothetical_exit_commission == second.hypothetical_exit_commission
    assert first.counterfactual_pnl == second.counterfactual_pnl


def test_saved_trend_down_loss_and_sacrificed_winner_are_classified() -> None:
    loser = evaluate_structural_failure_trade(
        _trade(pnl=Decimal("-10")),
        candles=_candles(execution_open=Decimal("99.5")),
    )
    winner = evaluate_structural_failure_trade(
        _trade(pnl=Decimal("5"), exit_reason="Trailing stop hit"),
        candles=_candles(execution_open=Decimal("98.5")),
    )
    assert loser.saved_loser is True
    assert loser.saved_trend_down_loss is True
    assert winner.sacrificed_winner is True


def test_gap_fails_closed_and_summary_reconciles_windows() -> None:
    candles = _candles()
    del candles[10]
    with pytest.raises(ValueError, match="gapless 1h candles"):
        evaluate_structural_failure_trade(_trade(), candles=candles)

    valid = _candles()
    trades = (
        _trade(pnl=Decimal("-10")),
        _trade(pnl=Decimal("5"), exit_reason="Trailing stop hit"),
    )
    summary = build_structural_failure_counterfactual(
        trades,
        candles_by_window={1: valid},
        symbol="BTCUSDT",
        base_seed=42,
    )
    assert summary.trades == 2
    assert summary.triggered == 2
    assert len(summary.by_window) == 1
    assert summary.pnl_delta == summary.counterfactual_pnl - summary.actual_pnl
