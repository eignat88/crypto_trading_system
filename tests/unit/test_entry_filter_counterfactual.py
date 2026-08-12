from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.backtest_engine import BacktestResult
from app.backtest.ema200_slope_p75_walk_forward import WindowThreshold
from app.backtest.portfolio import Portfolio
from app.backtest.walk_forward import WalkForwardWindow
from app.models import Fill, Order, Signal
from app.reporting.entry_filter_counterfactual import (
    reconstruct_window_counterfactual,
    summarize_counterfactual,
    summarize_features,
)

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _candles(slope: str = "0.002") -> list[dict]:
    rows = []
    for hour in range(30):
        close = Decimal("100") + Decimal(hour)
        rows.append(
            {
                "symbol": "BTCUSDT",
                "open_time": BASE + timedelta(hours=hour),
                "close": close,
                "indicators": {
                    "ema_20": close - Decimal("1"),
                    "ema_50": close - Decimal("2"),
                    "ema_200": close - Decimal("3"),
                    "ema200_slope_10": Decimal(slope),
                    "rsi": Decimal("42"),
                    "atr": Decimal("2"),
                    "volatility": Decimal("0.2"),
                    "regime": "TREND_UP",
                    "regime_confidence": Decimal("0.7"),
                },
            }
        )
    return rows


def _window() -> WalkForwardWindow:
    return WalkForwardWindow(
        index=1,
        train_start=BASE - timedelta(days=180),
        train_end=BASE,
        test_start=BASE,
        test_end=BASE + timedelta(days=60),
    )


def _backtest(*, entry_hour: int, exit_hour: int, entry_price: str, exit_price: str, reason: str) -> BacktestResult:
    entry_signal = Signal(
        action="open_long",
        symbol="BTCUSDT",
        price=Decimal(entry_price),
        quantity=Decimal("1"),
        timestamp=BASE + timedelta(hours=entry_hour),
        reason="Trend DCA base order",
        strategy="TrendDCA",
        parameters_version="trend_dca_v1",
        regime="TREND_UP",
    )
    exit_signal = Signal(
        action="close",
        symbol="BTCUSDT",
        price=Decimal(exit_price),
        quantity=Decimal("1"),
        timestamp=BASE + timedelta(hours=exit_hour - 1),
        reason=reason,
        strategy="TrendDCA",
        parameters_version="trend_dca_v1",
    )
    orders = [
        Order("o1", entry_signal, "buy", Decimal("1"), Decimal(entry_price), BASE + timedelta(hours=entry_hour)),
        Order("o2", exit_signal, "sell", Decimal("1"), Decimal(exit_price), BASE + timedelta(hours=exit_hour)),
    ]
    fills = [
        Fill("f1", "o1", "BTCUSDT", "buy", Decimal("1"), Decimal(entry_price), Decimal("0.1"), BASE + timedelta(hours=entry_hour + 1)),
        Fill("f2", "o2", "BTCUSDT", "sell", Decimal("1"), Decimal(exit_price), Decimal("0.1"), BASE + timedelta(hours=exit_hour)),
    ]
    pnl = Decimal(exit_price) - Decimal(entry_price) - Decimal("0.2")
    return BacktestResult(
        portfolio=Portfolio(Decimal("500")),
        total_trades=1,
        total_pnl=pnl,
        orders=orders,
        fills=fills,
    )


def test_labels_filtered_winner_from_baseline_outcome():
    candles = _candles("0.002")
    backtest = _backtest(entry_hour=10, exit_hour=15, entry_price="110", exit_price="116", reason="Take profit hit")
    records = reconstruct_window_counterfactual(
        symbol="BTCUSDT",
        window=_window(),
        threshold=WindowThreshold(1, 100, Decimal("0.003")),
        backtest=backtest,
        all_candles=candles,
    )
    assert len(records) == 1
    assert records[0].would_pass_p75 is False
    assert records[0].filter_group == "FILTERED_WINNER"
    assert records[0].realized_pnl == Decimal("5.8")


def test_labels_pass_td_loss_from_baseline_outcome():
    candles = _candles("0.004")
    backtest = _backtest(
        entry_hour=10,
        exit_hour=15,
        entry_price="110",
        exit_price="105",
        reason="Regime changed to TREND_DOWN",
    )
    record = reconstruct_window_counterfactual(
        symbol="BTCUSDT",
        window=_window(),
        threshold=WindowThreshold(1, 100, Decimal("0.003")),
        backtest=backtest,
        all_candles=candles,
    )[0]
    assert record.would_pass_p75 is True
    assert record.filter_group == "PASS_TD_LOSS"
    assert record.slope_margin_to_threshold == Decimal("0.001")


def test_summary_counts_filtered_good_and_bad():
    winner = reconstruct_window_counterfactual(
        symbol="BTCUSDT",
        window=_window(),
        threshold=WindowThreshold(1, 100, Decimal("0.003")),
        backtest=_backtest(entry_hour=10, exit_hour=15, entry_price="110", exit_price="116", reason="Take profit hit"),
        all_candles=_candles("0.002"),
    )[0]
    loss = reconstruct_window_counterfactual(
        symbol="BTCUSDT",
        window=_window(),
        threshold=WindowThreshold(1, 100, Decimal("0.003")),
        backtest=_backtest(entry_hour=10, exit_hour=15, entry_price="110", exit_price="105", reason="Regime changed to TREND_DOWN"),
        all_candles=_candles("0.002"),
    )[0]
    report = summarize_counterfactual(
        symbol="BTCUSDT", records=[winner, loss], baseline_oos_pnl=winner.realized_pnl + loss.realized_pnl
    )
    assert report.filtered_winner == 1
    assert report.filtered_td_loss == 1
    assert report.filtered_total == 2
    assert report.filtered_winner_share == Decimal("0.5")
    assert report.filtered_td_loss_share == Decimal("0.5")


def test_feature_summary_preserves_entry_features():
    record = reconstruct_window_counterfactual(
        symbol="BTCUSDT",
        window=_window(),
        threshold=WindowThreshold(1, 100, Decimal("0.003")),
        backtest=_backtest(entry_hour=10, exit_hour=15, entry_price="110", exit_price="116", reason="Trailing stop hit"),
        all_candles=_candles("0.002"),
    )[0]
    summary = summarize_features([record])
    assert summary.trades == 1
    assert summary.average_rsi == Decimal("42")
    assert summary.average_ema200_slope_10 == Decimal("0.002")
    assert summary.average_close_to_ema200 is not None
    assert summary.average_trend_up_age_bars == Decimal("11")


def test_rejects_pnl_reconciliation_mismatch():
    candles = _candles("0.002")
    backtest = _backtest(entry_hour=10, exit_hour=15, entry_price="110", exit_price="116", reason="Take profit hit")
    backtest.total_pnl = Decimal("999")
    with pytest.raises(ValueError, match="PnL reconciliation failed"):
        reconstruct_window_counterfactual(
            symbol="BTCUSDT",
            window=_window(),
            threshold=WindowThreshold(1, 100, Decimal("0.003")),
            backtest=backtest,
            all_candles=candles,
        )


def test_rejects_missing_entry_slope():
    candles = _candles("0.002")
    candles[10]["indicators"]["ema200_slope_10"] = None
    backtest = _backtest(entry_hour=10, exit_hour=15, entry_price="110", exit_price="116", reason="Take profit hit")
    with pytest.raises(ValueError, match="Entry has no ema200_slope_10"):
        reconstruct_window_counterfactual(
            symbol="BTCUSDT",
            window=_window(),
            threshold=WindowThreshold(1, 100, Decimal("0.003")),
            backtest=backtest,
            all_candles=candles,
        )
