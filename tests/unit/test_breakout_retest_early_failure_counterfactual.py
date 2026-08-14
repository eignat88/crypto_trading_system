from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_early_failure_counterfactual import (
    build_early_failure_counterfactual,
    evaluate_early_failure_trade,
)

T0=datetime(2026,1,1,tzinfo=UTC)

def trade(*,pnl=Decimal("-1"),exit_hours=60,exit_reason="Regime changed to TREND_DOWN"):
    return BreakoutRetestTrade(symbol="BTCUSDT",window_index=1,breakout_time=T0-timedelta(hours=2),breakout_level=Decimal("99"),breakout_close=Decimal("101"),breakout_strength_pct=Decimal("0.02"),retest_time=T0-timedelta(hours=1),bars_to_retest=1,retest_low=Decimal("99"),retest_close=Decimal("100"),retest_depth_pct=Decimal("0"),retest_close_offset_pct=Decimal("0.01"),entry_fill_time=T0,entry_price=Decimal("100"),quantity=Decimal("1"),entry_regime="TREND_UP",entry_ema50=Decimal("101"),entry_ema200=Decimal("99"),entry_volatility=Decimal("0.1"),exit_time=T0+timedelta(hours=exit_hours),exit_price=Decimal("99"),exit_reason=exit_reason,entry_commission=Decimal("0.1"),exit_commission=Decimal("0.1"),realized_pnl=pnl,holding_bars=exit_hours)

def candles(h24=Decimal("99"),next_open=Decimal("98"),hours=70):
    rows=[]
    for i in range(hours):
        close=Decimal("100")
        if i==24: close=h24
        rows.append({"symbol":"BTCUSDT","open_time":T0+timedelta(hours=i),"open":next_open if i==25 else close,"high":close+1,"low":close-1,"close":close,"indicators":{}})
    return rows

def test_triggers_only_when_24h_close_strictly_below_entry():
    assert evaluate_early_failure_trade(trade(),candles=candles(Decimal("99"))).triggered
    assert not evaluate_early_failure_trade(trade(),candles=candles(Decimal("100"))).triggered

def test_counterfactual_executes_at_next_hour_open():
    r=evaluate_early_failure_trade(trade(),candles=candles(next_open=Decimal("97")),base_seed=42)
    assert r.triggered and r.hypothetical_exit_time==T0+timedelta(hours=25)
    assert r.hypothetical_reference_price==Decimal("97")

def test_does_not_trigger_if_actual_exit_is_on_or_before_n_plus_one():
    assert not evaluate_early_failure_trade(trade(exit_hours=25),candles=candles()).triggered
    assert not evaluate_early_failure_trade(trade(exit_hours=20),candles=candles()).triggered

def test_execution_cost_is_deterministic():
    a=evaluate_early_failure_trade(trade(),candles=candles(),base_seed=42)
    b=evaluate_early_failure_trade(trade(),candles=candles(),base_seed=42)
    assert a.hypothetical_execution_price==b.hypothetical_execution_price
    assert a.counterfactual_pnl==b.counterfactual_pnl

def test_saved_loser_and_sacrificed_winner_are_reported():
    loser=evaluate_early_failure_trade(trade(pnl=Decimal("-10")),candles=candles(next_open=Decimal("99")))
    winner=evaluate_early_failure_trade(trade(pnl=Decimal("5")),candles=candles(next_open=Decimal("98")))
    assert loser.saved_loser
    assert winner.sacrificed_winner

def test_no_horizon_candle_means_no_counterfactual():
    r=evaluate_early_failure_trade(trade(),candles=candles(hours=20))
    assert not r.triggered and r.counterfactual_pnl==r.actual_pnl

def test_hourly_gap_fails_closed():
    rows=candles(); del rows[10]
    with pytest.raises(ValueError,match="Hourly candle gap"):
        evaluate_early_failure_trade(trade(),candles=rows)

def test_summary_reconciles_trade_level_deltas():
    trades=(trade(pnl=Decimal("-10")),trade(pnl=Decimal("2"),exit_hours=50,exit_reason="Trailing stop hit"))
    s=build_early_failure_counterfactual(trades,candles_by_window={1:candles()},symbol="BTCUSDT",base_seed=42)
    assert s.trades==2
    assert s.actual_pnl==Decimal("-8")
    assert s.counterfactual_pnl==sum((x.counterfactual_pnl for x in s.trades_detail),Decimal("0"))
    assert s.pnl_delta==s.counterfactual_pnl-s.actual_pnl
