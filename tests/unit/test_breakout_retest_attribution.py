from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.backtest_engine import BacktestResult
from app.models import Fill, Order, Signal
from app.reporting.breakout_retest_attribution import (
    build_breakout_retest_attribution,
    reconstruct_breakout_retest_trades,
)

UTC = timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)
SYMBOL = "BTCUSDT"


def _entry_signal() -> Signal:
    return Signal(
        action="open_long",
        symbol=SYMBOL,
        price=Decimal("101"),
        quantity=Decimal("0.1"),
        timestamp=T0,
        reason="Breakout retest held",
        strategy="BreakoutRetest",
        parameters_version="breakout_retest_v1",
        regime="TREND_UP",
        indicators={
            "ema_50": Decimal("99"),
            "ema_200": Decimal("90"),
            "volatility": Decimal("0.12"),
        },
        metadata={
            "breakout_time": (T0 - timedelta(hours=3)).isoformat(),
            "retest_time": T0.isoformat(),
            "breakout_level": "100",
            "breakout_close": "102",
            "retest_low": "99",
            "retest_close": "101",
            "bars_since_breakout": 3,
            "resistance_lookback_bars": 20,
            "retest_timeout_bars": 24,
        },
    )


def _result(
    *,
    exit_price: Decimal = Decimal("110"),
    exit_reason: str = "Take profit hit",
    total_pnl: Decimal | None = None,
) -> BacktestResult:
    entry_signal = _entry_signal()
    exit_signal = Signal(
        action="close",
        symbol=SYMBOL,
        price=exit_price,
        quantity=Decimal("0.1"),
        timestamp=T0 + timedelta(hours=10),
        reason=exit_reason,
        strategy="BreakoutRetest",
        parameters_version="breakout_retest_v1",
    )
    buy_order = Order(
        order_id="o1",
        signal=entry_signal,
        side="buy",
        quantity=Decimal("0.1"),
        requested_price=Decimal("101"),
        created_at=T0,
    )
    sell_order = Order(
        order_id="o2",
        signal=exit_signal,
        side="sell",
        quantity=Decimal("0.1"),
        requested_price=exit_price,
        created_at=T0 + timedelta(hours=10),
    )
    buy_fill = Fill(
        fill_id="f1",
        order_id="o1",
        symbol=SYMBOL,
        side="buy",
        quantity=Decimal("0.1"),
        price=Decimal("101.1"),
        commission=Decimal("0.01"),
        timestamp=T0 + timedelta(hours=1),
    )
    sell_fill = Fill(
        fill_id="f2",
        order_id="o2",
        symbol=SYMBOL,
        side="sell",
        quantity=Decimal("0.1"),
        price=exit_price,
        commission=Decimal("0.02"),
        timestamp=T0 + timedelta(hours=10),
    )
    pnl = (exit_price - Decimal("101.1")) * Decimal("0.1") - Decimal("0.03")
    return BacktestResult(
        portfolio=object(),
        total_trades=1,
        total_pnl=pnl if total_pnl is None else total_pnl,
        orders=[buy_order, sell_order],
        fills=[buy_fill, sell_fill],
    )


def test_reconstructs_trade_and_structural_features() -> None:
    trade = reconstruct_breakout_retest_trades(
        _result(), symbol=SYMBOL, window_index=2
    )[0]

    assert trade.window_index == 2
    assert trade.breakout_strength_pct == Decimal("0.02")
    assert trade.retest_depth_pct == Decimal("0.01")
    assert trade.retest_close_offset_pct == Decimal("0.01")
    assert trade.bars_to_retest == 3
    assert trade.holding_bars == 9
    assert trade.entry_regime == "TREND_UP"
    assert trade.entry_ema50 == Decimal("99")
    assert trade.entry_ema200 == Decimal("90")
    assert trade.entry_volatility == Decimal("0.12")
    assert trade.outcome == "WINNER"


def test_realized_pnl_includes_both_commissions() -> None:
    trade = reconstruct_breakout_retest_trades(
        _result(exit_price=Decimal("110")), symbol=SYMBOL, window_index=1
    )[0]
    assert trade.realized_pnl == Decimal("0.86")


def test_missing_matching_order_fails_closed() -> None:
    result = _result()
    result.orders = result.orders[:1]
    with pytest.raises(ValueError, match="no matching order"):
        reconstruct_breakout_retest_trades(result, symbol=SYMBOL, window_index=1)


def test_multiple_buy_fills_fail_closed_because_dca_is_disabled() -> None:
    result = _result()
    result.fills.insert(1, result.fills[0])
    with pytest.raises(ValueError, match="multiple buy fills"):
        reconstruct_breakout_retest_trades(result, symbol=SYMBOL, window_index=1)


def test_close_quantity_mismatch_fails_closed() -> None:
    result = _result()
    sell = result.fills[1]
    result.fills[1] = Fill(
        fill_id=sell.fill_id,
        order_id=sell.order_id,
        symbol=sell.symbol,
        side=sell.side,
        quantity=Decimal("0.05"),
        price=sell.price,
        commission=sell.commission,
        timestamp=sell.timestamp,
    )
    with pytest.raises(ValueError, match="quantity mismatch"):
        reconstruct_breakout_retest_trades(result, symbol=SYMBOL, window_index=1)


def test_pnl_reconciliation_failure_blocks_report() -> None:
    with pytest.raises(ValueError, match="PnL reconciliation failed"):
        reconstruct_breakout_retest_trades(
            _result(total_pnl=Decimal("999")), symbol=SYMBOL, window_index=1
        )


def test_attribution_groups_exit_regime_window_and_outcome() -> None:
    winner = reconstruct_breakout_retest_trades(
        _result(exit_reason="Take profit hit"), symbol=SYMBOL, window_index=1
    )[0]
    loser = reconstruct_breakout_retest_trades(
        _result(exit_price=Decimal("95"), exit_reason="Regime changed to TREND_DOWN"),
        symbol=SYMBOL,
        window_index=2,
    )[0]

    attribution = build_breakout_retest_attribution((winner, loser), symbol=SYMBOL)

    assert attribution.total_trades == 2
    assert {item.key for item in attribution.by_exit_reason} == {
        "Take profit hit",
        "Regime changed to TREND_DOWN",
    }
    assert [item.key for item in attribution.by_entry_regime] == ["TREND_UP"]
    assert {item.key for item in attribution.by_window} == {"w01", "w02"}
    assert {item.key for item in attribution.by_outcome} == {"WINNER", "LOSER"}


def test_feature_stats_are_descriptive_and_split_by_outcome() -> None:
    winner = reconstruct_breakout_retest_trades(
        _result(), symbol=SYMBOL, window_index=1
    )[0]
    loser = reconstruct_breakout_retest_trades(
        _result(exit_price=Decimal("95"), exit_reason="Regime changed to TREND_DOWN"),
        symbol=SYMBOL,
        window_index=2,
    )[0]
    attribution = build_breakout_retest_attribution((winner, loser), symbol=SYMBOL)

    stats = {
        (item.feature, item.outcome): item
        for item in attribution.feature_stats
    }
    assert stats[("breakout_strength_pct", "WINNER")].mean == Decimal("0.02")
    assert stats[("breakout_strength_pct", "LOSER")].median == Decimal("0.02")
    assert stats[("bars_to_retest", "ALL")].count == 2
    assert stats[("holding_bars", "ALL")].mean == Decimal("9")
