from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_failed_structure_counterfactual import FailedStructureTradeResult
from app.reporting.breakout_retest_failed_structure_false_positive_attribution import (
    build_false_positive_attribution_trade,
    build_false_positive_stats,
    categorical_counts,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _trade(*, pnl: Decimal = Decimal("-2"), exit_reason: str = "Regime changed to TREND_DOWN") -> BreakoutRetestTrade:
    return BreakoutRetestTrade(
        symbol="BTCUSDT", window_index=1,
        breakout_time=T0-timedelta(hours=2), breakout_level=Decimal("100"), breakout_close=Decimal("101"), breakout_strength_pct=Decimal("0.01"),
        retest_time=T0-timedelta(hours=1), bars_to_retest=2, retest_low=Decimal("99"), retest_close=Decimal("100.2"), retest_depth_pct=Decimal("0.01"), retest_close_offset_pct=Decimal("0.002"),
        entry_fill_time=T0, entry_price=Decimal("100"), quantity=Decimal("1"), entry_regime="TREND_UP", entry_ema50=Decimal("99"), entry_ema200=Decimal("95"), entry_volatility=Decimal("0.1"),
        exit_time=T0+timedelta(hours=50), exit_price=Decimal("96"), exit_reason=exit_reason,
        entry_commission=Decimal("0.1"), exit_commission=Decimal("0.1"), realized_pnl=pnl, holding_bars=50,
    )


def _result(*, saved: bool = True, sacrificed: bool = False, triggered: bool = True, actual_pnl: Decimal = Decimal("-2"), cf_pnl: Decimal = Decimal("-1")) -> FailedStructureTradeResult:
    return FailedStructureTradeResult(
        symbol="BTCUSDT", window_index=1, entry_fill_time=T0,
        actual_exit_time=T0+timedelta(hours=50), actual_exit_reason="Regime changed to TREND_DOWN",
        actual_pnl=actual_pnl, actual_outcome="LOSER" if actual_pnl < 0 else "WINNER",
        snapshot_time=T0+timedelta(hours=23), snapshot_close=Decimal("98"), snapshot_ema20=Decimal("99"), snapshot_ema50=Decimal("99.5"), breakout_level=Decimal("100"),
        below_ema20=True, below_ema50=True, below_breakout_level=True, triggered=triggered,
        hypothetical_exit_time=T0+timedelta(hours=24), hypothetical_reference_price=Decimal("97.8"), hypothetical_execution_price=Decimal("97.7"), hypothetical_exit_commission=Decimal("0.1"),
        counterfactual_pnl=cf_pnl, pnl_delta=cf_pnl-actual_pnl,
        sacrificed_winner=sacrificed, saved_loser=saved,
    )


def _candles() -> list[dict]:
    rows=[]
    for hour in range(60):
        close=Decimal("101")
        high=Decimal("102")
        low=Decimal("99")
        if hour == 23:
            close=Decimal("98"); high=Decimal("99"); low=Decimal("97")
        if hour == 24:
            close=Decimal("99"); high=Decimal("100"); low=Decimal("96")
        if hour == 30:
            high=Decimal("110")
        if hour == 40:
            low=Decimal("90")
        rows.append({
            "symbol":"BTCUSDT", "open_time":T0+timedelta(hours=hour),
            "open":close, "high":high, "low":low, "close":close,
            "indicators":{
                "ema_20":Decimal("99"), "ema_50":Decimal("99.5"), "ema_200":Decimal("95"),
                "atr":Decimal("1"), "volatility":Decimal("0.1"), "regime":"TREND_UP", "regime_confidence":Decimal("0.8")
            }
        })
    return rows


def test_saved_loser_group_and_causal_snapshot_features() -> None:
    item=build_false_positive_attribution_trade(_trade(), _result(), candles=_candles())
    assert item.group == "SAVED_LOSER"
    assert item.snapshot_time == T0+timedelta(hours=23)
    assert item.return_24h_pct == Decimal("-0.02")
    assert item.distance_to_breakout_level_pct == Decimal("-0.02")


def test_sacrificed_winner_group() -> None:
    trade=_trade(pnl=Decimal("3"), exit_reason="Trailing stop hit")
    result=_result(saved=False, sacrificed=True, actual_pnl=Decimal("3"), cf_pnl=Decimal("-1"))
    item=build_false_positive_attribution_trade(trade, result, candles=_candles())
    assert item.group == "SACRIFICED_WINNER"


def test_other_trigger_group() -> None:
    item=build_false_positive_attribution_trade(_trade(), _result(saved=False), candles=_candles())
    assert item.group == "OTHER_TRIGGER"


def test_non_triggered_trade_is_rejected() -> None:
    with pytest.raises(ValueError, match="triggered trades only"):
        build_false_positive_attribution_trade(_trade(), _result(triggered=False), candles=_candles())


def test_future_excursions_start_after_snapshot_and_exclude_exit_ohlc() -> None:
    item=build_false_positive_attribution_trade(_trade(), _result(), candles=_candles())
    # Future high 110 at hour 30 and low 90 at hour 40 are measured from snapshot close 98.
    assert item.future_mfe_after_24h_pct == (Decimal("110")-Decimal("98"))/Decimal("98")
    assert item.future_mae_after_24h_pct == (Decimal("90")-Decimal("98"))/Decimal("98")
    assert item.holding_after_24h_bars == 26


def test_future_candle_does_not_change_causal_24h_return() -> None:
    candles=_candles()
    baseline=build_false_positive_attribution_trade(_trade(), _result(), candles=candles)
    candles[30]["high"]=Decimal("1000")
    changed=build_false_positive_attribution_trade(_trade(), _result(), candles=candles)
    assert changed.return_24h_pct == baseline.return_24h_pct
    assert changed.mfe_24h_pct == baseline.mfe_24h_pct
    assert changed.future_mfe_after_24h_pct > baseline.future_mfe_after_24h_pct


def test_gap_fails_closed() -> None:
    candles=_candles(); del candles[10]
    with pytest.raises(ValueError, match="gapless 1h candles"):
        build_false_positive_attribution_trade(_trade(), _result(), candles=candles)


def test_stats_and_categorical_counts_preserve_groups() -> None:
    saved=build_false_positive_attribution_trade(_trade(), _result(), candles=_candles())
    winner=build_false_positive_attribution_trade(
        _trade(pnl=Decimal("3"), exit_reason="Trailing stop hit"),
        _result(saved=False, sacrificed=True, actual_pnl=Decimal("3"), cf_pnl=Decimal("-1")),
        candles=_candles(),
    )
    stats=build_false_positive_stats((saved,winner))
    saved_return=next(x for x in stats if x.feature=="return_24h_pct" and x.group=="SAVED_LOSER")
    assert saved_return.count == 1
    assert categorical_counts((saved,winner), field="actual_exit_reason", group="SACRIFICED_WINNER") == {"Trailing stop hit":1}
