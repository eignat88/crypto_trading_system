from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.reporting.backtest_attribution import reconstruct_closed_trades


def _row(*, side: str, quantity: str, price: str, commission: str, hour: int, regime=None, reason=None):
    signal = {}
    if regime is not None:
        signal["regime"] = regime
    if reason is not None:
        signal["reason"] = reason
    return {
        "symbol": "BTCUSDT",
        "side": side,
        "quantity": Decimal(quantity),
        "price": Decimal(price),
        "commission": Decimal(commission),
        "fill_time": datetime(2026, 1, 1, hour, tzinfo=UTC),
        "signal": signal,
    }


def test_reconstruct_single_trade_matches_portfolio_formula():
    trades = reconstruct_closed_trades([
        _row(side="buy", quantity="1", price="100", commission="0.1", hour=1, regime="TREND_UP"),
        _row(side="sell", quantity="1", price="110", commission="0.11", hour=2, reason="Take-profit hit"),
    ])

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_regime == "TREND_UP"
    assert trade.exit_reason == "Take-profit hit"
    assert trade.pnl == Decimal("9.79")


def test_reconstruct_dca_uses_weighted_entry_and_all_entry_commissions():
    trades = reconstruct_closed_trades([
        _row(side="buy", quantity="1", price="100", commission="0.1", hour=1, regime="TREND_UP"),
        _row(side="buy", quantity="1", price="80", commission="0.08", hour=2, regime="TREND_UP"),
        _row(side="sell", quantity="2", price="95", commission="0.19", hour=3, reason="Trailing stop"),
    ])

    trade = trades[0]
    assert trade.quantity == Decimal("2")
    assert trade.entry_price == Decimal("90")
    assert trade.entry_commission == Decimal("0.18")
    assert trade.pnl == Decimal("9.63")


def test_reconstruct_rejects_unmatched_sell():
    with pytest.raises(ValueError, match="Sell fill without an open spot position"):
        reconstruct_closed_trades([
            _row(side="sell", quantity="1", price="100", commission="0.1", hour=1, reason="Stop-loss hit")
        ])


def test_reconstruct_allows_numeric_38_18_rounding_delta():
    trades = reconstruct_closed_trades([
        _row(
            side="buy",
            quantity="0.000190492350294829",
            price="100",
            commission="0",
            hour=1,
            regime="TREND_UP",
        ),
        _row(
            side="sell",
            quantity="0.000190492350294830",
            price="110",
            commission="0",
            hour=2,
            reason="Take-profit hit",
        ),
    ])

    assert len(trades) == 1
    assert trades[0].quantity == Decimal("0.000190492350294829")


def test_reconstruct_rejects_material_quantity_mismatch():
    with pytest.raises(ValueError, match="Partial/oversized sell"):
        reconstruct_closed_trades([
            _row(
                side="buy",
                quantity="0.000190492350294829",
                price="100",
                commission="0",
                hour=1,
                regime="TREND_UP",
            ),
            _row(
                side="sell",
                quantity="0.000190492450294829",
                price="110",
                commission="0",
                hour=2,
                reason="Take-profit hit",
            ),
        ])
