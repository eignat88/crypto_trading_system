from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest

from app.backtest.commission_model import CommissionConfig
from app.reporting.trend_down_diagnostics import (
    reconstruct_trend_down_exits,
    summarize_trend_down_diagnostics,
)

UTC = UTC


def _fill(*, side: str, qty: str, price: str, fee: str, hour: int, reason: str = "", signal_price: str | None = None):
    signal = {
        "reason": reason,
        "timestamp": datetime(2026, 1, 1, hour - 1 if side == "sell" else hour, tzinfo=UTC).isoformat(),
        "price": signal_price or price,
    }
    return {
        "side": side,
        "quantity": Decimal(qty),
        "price": Decimal(price),
        "commission": Decimal(fee),
        "fill_time": datetime(2026, 1, 1, hour, tzinfo=UTC),
        "signal": signal,
    }


def _candle(hour: int, close: str, low: str, high: str, regime: str):
    return {
        "open_time": datetime(2026, 1, 1, hour, tzinfo=UTC),
        "close_price": Decimal(close),
        "low_price": Decimal(low),
        "high_price": Decimal(high),
        "regime": regime,
    }


def test_reconstructs_dca_and_three_bar_continuation():
    run_id = uuid4()
    fills = [
        _fill(side="buy", qty="1", price="100", fee="0.1", hour=1),
        _fill(side="buy", qty="1", price="80", fee="0.08", hour=2),
        _fill(
            side="sell",
            qty="2",
            price="84",
            fee="0.168",
            hour=4,
            reason="Regime changed to TREND_DOWN",
            signal_price="85",
        ),
    ]
    candles = [
        _candle(4, "84", "83", "86", "TREND_DOWN"),
        _candle(5, "82", "81", "85", "TREND_DOWN"),
        _candle(6, "80", "79", "83", "TREND_DOWN"),
    ]

    records = reconstruct_trend_down_exits(
        run_id=run_id,
        symbol="BTCUSDT",
        fill_rows=fills,
        candle_rows=candles,
        commission_config=CommissionConfig(),
        bar_delta=timedelta(hours=1),
    )

    assert len(records) == 1
    item = records[0]
    assert item.dca_count == 1
    assert item.entry_price == Decimal("100")
    assert item.weighted_entry_price == Decimal("90")
    assert item.first_trend_down_price == Decimal("85")
    assert item.price_after_1_bar == Decimal("84")
    assert item.price_after_2_bars == Decimal("82")
    assert item.price_after_3_bars == Decimal("80")
    assert item.min_low_next_3_bars == Decimal("79")
    assert item.max_high_next_3_bars == Decimal("86")
    assert item.trend_down_continued_3_bars is True
    assert item.false_switch_within_3_bars is False
    assert item.actual_realized_pnl == Decimal("-12.348")


def test_marks_false_switch_when_regime_recovers_within_three_bars():
    fills = [
        _fill(side="buy", qty="1", price="100", fee="0.1", hour=1),
        _fill(
            side="sell",
            qty="1",
            price="94",
            fee="0.094",
            hour=4,
            reason="Regime changed to TREND_DOWN",
            signal_price="95",
        ),
    ]
    candles = [
        _candle(4, "96", "93", "97", "RANGE"),
        _candle(5, "99", "95", "100", "TREND_UP"),
        _candle(6, "101", "98", "102", "TREND_UP"),
    ]

    records = reconstruct_trend_down_exits(
        run_id=uuid4(),
        symbol="BTCUSDT",
        fill_rows=fills,
        candle_rows=candles,
        commission_config=CommissionConfig(),
    )

    item = records[0]
    assert item.trend_down_continued_3_bars is False
    assert item.false_switch_within_3_bars is True
    assert item.close_return_3_bars > 0


def test_summary_counts_continuation_and_price_direction():
    fills = [
        _fill(side="buy", qty="1", price="100", fee="0.1", hour=1),
        _fill(
            side="sell",
            qty="1",
            price="94",
            fee="0.094",
            hour=4,
            reason="Regime changed to TREND_DOWN",
            signal_price="95",
        ),
    ]
    candles = [
        _candle(4, "94", "93", "96", "TREND_DOWN"),
        _candle(5, "93", "92", "95", "TREND_DOWN"),
        _candle(6, "92", "91", "94", "TREND_DOWN"),
    ]
    run_id = uuid4()
    records = reconstruct_trend_down_exits(
        run_id=run_id,
        symbol="BTCUSDT",
        fill_rows=fills,
        candle_rows=candles,
        commission_config=CommissionConfig(),
    )
    report = summarize_trend_down_diagnostics(
        run_id=run_id,
        symbol="BTCUSDT",
        interval="1h",
        records=records,
    )

    assert report.total_exits == 1
    assert report.continued_3_bars == 1
    assert report.false_switches_within_3_bars == 0
    assert report.price_lower_after_1_bar == 1
    assert report.price_lower_after_2_bars == 1
    assert report.price_lower_after_3_bars == 1


def test_rejects_material_partial_sell():
    fills = [
        _fill(side="buy", qty="1", price="100", fee="0.1", hour=1),
        _fill(
            side="sell",
            qty="0.9",
            price="94",
            fee="0.09",
            hour=4,
            reason="Regime changed to TREND_DOWN",
            signal_price="95",
        ),
    ]

    with pytest.raises(ValueError, match="Partial/oversized sell"):
        reconstruct_trend_down_exits(
            run_id=uuid4(),
            symbol="BTCUSDT",
            fill_rows=fills,
            candle_rows=[],
            commission_config=CommissionConfig(),
        )
