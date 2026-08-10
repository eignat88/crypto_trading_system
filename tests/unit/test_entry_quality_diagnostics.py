from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.reporting.entry_quality_diagnostics import reconstruct_entry_quality, summarize_group

UTC = timezone.utc


def _signal(ts: datetime, *, price: str, reason: str = "", regime: str = "TREND_UP") -> dict:
    return {"timestamp": ts.isoformat(), "price": price, "reason": reason, "regime": regime}


def _fill(*, side: str, qty: str, price: str, fee: str, fill_hour: int, signal: dict) -> dict:
    return {
        "side": side,
        "quantity": Decimal(qty),
        "price": Decimal(price),
        "commission": Decimal(fee),
        "fill_time": datetime(2026, 1, 1, fill_hour, tzinfo=UTC),
        "signal": signal,
    }


def _candles(regimes: list[str]) -> list[dict]:
    rows = []
    for hour, regime in enumerate(regimes):
        base = Decimal("100") + Decimal(hour)
        rows.append({
            "open_time": datetime(2026, 1, 1, hour, tzinfo=UTC),
            "close_price": base,
            "ema_20": base - Decimal("1"),
            "ema_50": base - Decimal("2"),
            "ema_200": base - Decimal("3"),
            "rsi": Decimal("42"),
            "atr": Decimal("2"),
            "volatility": Decimal("0.2"),
            "regime": regime,
            "regime_confidence": Decimal("0.7"),
        })
    return rows


def test_reconstructs_trend_down_loss_entry_quality_and_age():
    candles = _candles(["RANGE"] + ["TREND_UP"] * 11 + ["TREND_DOWN"] * 3)
    entry_signal_time = datetime(2026, 1, 1, 10, tzinfo=UTC)
    exit_signal_time = datetime(2026, 1, 1, 12, tzinfo=UTC)
    fills = [
        _fill(side="buy", qty="1", price="111", fee="0.111", fill_hour=11,
              signal=_signal(entry_signal_time, price="110")),
        _fill(side="sell", qty="1", price="108", fee="0.108", fill_hour=13,
              signal=_signal(exit_signal_time, price="109", reason="Regime changed to TREND_DOWN", regime="TREND_DOWN")),
    ]

    records = reconstruct_entry_quality(
        run_id=uuid4(), symbol="BTCUSDT", fill_rows=fills, candle_rows=candles
    )

    assert len(records) == 1
    item = records[0]
    assert item.outcome_group == "TREND_DOWN_LOSS"
    assert item.trend_up_age_bars == 10
    assert item.trend_up_age_censored is False
    assert item.trend_down_before_exit is True
    assert item.time_to_trend_down_hours == Decimal("2")
    assert item.ema20_slope_10 is not None
    assert item.ema50_slope_10 is not None
    assert item.ema200_slope_10 is not None
    assert item.close_to_ema200 > 0


def test_classifies_tp_and_trailing_as_winners():
    candles = _candles(["TREND_UP"] * 15)
    fills = [
        _fill(side="buy", qty="1", price="105", fee="0.105", fill_hour=5,
              signal=_signal(datetime(2026, 1, 1, 4, tzinfo=UTC), price="104")),
        _fill(side="sell", qty="1", price="110", fee="0.110", fill_hour=8,
              signal=_signal(datetime(2026, 1, 1, 7, tzinfo=UTC), price="109", reason="Take-profit hit")),
        _fill(side="buy", qty="1", price="110", fee="0.110", fill_hour=10,
              signal=_signal(datetime(2026, 1, 1, 9, tzinfo=UTC), price="109")),
        _fill(side="sell", qty="1", price="114", fee="0.114", fill_hour=14,
              signal=_signal(datetime(2026, 1, 1, 13, tzinfo=UTC), price="113", reason="Trailing stop hit")),
    ]

    records = reconstruct_entry_quality(
        run_id=uuid4(), symbol="BTCUSDT", fill_rows=fills, candle_rows=candles
    )
    assert [r.outcome_group for r in records] == ["WINNER", "WINNER"]
    assert all(r.trend_down_before_exit is False for r in records)


def test_marks_age_censored_at_start_of_available_history():
    candles = _candles(["TREND_UP"] * 12)
    fills = [
        _fill(side="buy", qty="1", price="103", fee="0.103", fill_hour=3,
              signal=_signal(datetime(2026, 1, 1, 2, tzinfo=UTC), price="102")),
        _fill(side="sell", qty="1", price="106", fee="0.106", fill_hour=6,
              signal=_signal(datetime(2026, 1, 1, 5, tzinfo=UTC), price="105", reason="Take profit hit")),
    ]
    item = reconstruct_entry_quality(
        run_id=uuid4(), symbol="ETHUSDT", fill_rows=fills, candle_rows=candles
    )[0]
    assert item.trend_up_age_bars == 3
    assert item.trend_up_age_censored is True


def test_summary_compares_numeric_entry_features():
    candles = _candles(["RANGE"] + ["TREND_UP"] * 11 + ["TREND_DOWN"] * 3)
    fills = [
        _fill(side="buy", qty="1", price="106", fee="0.106", fill_hour=6,
              signal=_signal(datetime(2026, 1, 1, 5, tzinfo=UTC), price="105")),
        _fill(side="sell", qty="1", price="110", fee="0.110", fill_hour=9,
              signal=_signal(datetime(2026, 1, 1, 8, tzinfo=UTC), price="108", reason="Trailing stop hit")),
    ]
    records = reconstruct_entry_quality(
        run_id=uuid4(), symbol="BTCUSDT", fill_rows=fills, candle_rows=candles
    )
    summary = summarize_group("WINNER", records)
    assert summary.trades == 1
    assert summary.average_rsi == Decimal("42")
    assert summary.average_trend_up_age_bars == Decimal("5")
    assert summary.average_pnl > 0


def test_rejects_material_partial_sell():
    candles = _candles(["TREND_UP"] * 12)
    fills = [
        _fill(side="buy", qty="1", price="103", fee="0.103", fill_hour=3,
              signal=_signal(datetime(2026, 1, 1, 2, tzinfo=UTC), price="102")),
        _fill(side="sell", qty="0.9", price="100", fee="0.09", fill_hour=6,
              signal=_signal(datetime(2026, 1, 1, 5, tzinfo=UTC), price="100", reason="Regime changed to TREND_DOWN", regime="TREND_DOWN")),
    ]
    with pytest.raises(ValueError, match="Partial/oversized sell"):
        reconstruct_entry_quality(
            run_id=uuid4(), symbol="BTCUSDT", fill_rows=fills, candle_rows=candles
        )
