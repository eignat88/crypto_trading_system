from datetime import datetime
from decimal import Decimal

from app.models import SignalAction
from app.strategies.cts_backtest_strategy import CTSBacktestStrategy


def test_cts_strategy_exposes_adapter_signal():
    strategy = CTSBacktestStrategy(["BTCUSDT"])
    strategy.state.update(
        {
            "pullback_state": "LOCKED",
            "cooldown_ready": True,
            "dca_signal": True,
            "regime": "BULL",
        }
    )

    signal = strategy.should_enter(
        {
            "symbol": "BTCUSDT",
            "close": "60000",
            "timestamp": datetime(2026, 8, 13),
        },
        {"ema200": Decimal("58000")},
        {},
    )

    assert signal is not None
    assert signal.action == SignalAction.BUY


def test_cts_strategy_waits_without_confirmation():
    strategy = CTSBacktestStrategy(["BTCUSDT"])
    strategy.state.update(
        {
            "pullback_state": "WAIT_PULLBACK",
            "cooldown_ready": True,
            "dca_signal": True,
        }
    )

    assert strategy.should_enter({}, {}, {}) is None
