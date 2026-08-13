from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

from app.models import SignalAction
from app.strategies.cts_backtest_strategy import CTSBacktestStrategy


FIXTURE = Path(__file__).parents[1] / "fixtures" / "tradingview" / "cts_v23_btcusdt_1h.csv"


def test_cts_strategy_reproduces_tradingview_dca_fixture_state() -> None:
    """Verify that the existing CTS strategy adapter can consume TV fixture state.

    This is intentionally a signal-layer test only. It does not validate
    BacktestEngine, Risk Engine or execution lifecycle.
    """

    with FIXTURE.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    tv_rows = [row for row in rows if row["TV_DCA_SIGNAL"] == "1"]
    assert len(tv_rows) == 1

    tv_row = tv_rows[0]

    strategy = CTSBacktestStrategy(["BTCUSDT"])
    strategy.state.update(
        {
            "pullback_state": "LOCKED",
            "cooldown_ready": True,
            "dca_signal": True,
            "regime": "UNKNOWN",
        }
    )

    signal = strategy.should_enter(
        {
            "symbol": "BTCUSDT",
            "close": tv_row["close"],
            "timestamp": datetime.fromtimestamp(int(tv_row["time"]), tz=UTC),
        },
        {
            "source": "tradingview_fixture",
        },
        {},
    )

    assert signal is not None
    assert signal.action == SignalAction.BUY
    assert signal.timestamp == datetime.fromtimestamp(int(tv_row["time"]), tz=UTC)
