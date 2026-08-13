from datetime import datetime
from decimal import Decimal

from app.models import SignalAction
from app.strategies.cts_backtest_adapter import CTSBacktestAdapter


def test_locked_cts_state_creates_buy_signal():
    adapter = CTSBacktestAdapter()

    signal = adapter.generate_signal(
        candle={
            "symbol": "BTCUSDT",
            "close": "60000",
            "timestamp": datetime(2026, 8, 13),
        },
        indicators={"ema200": Decimal("58000")},
        state={
            "pullback_state": "LOCKED",
            "cooldown_ready": True,
            "dca_signal": True,
            "regime": "BULL",
        },
    )

    assert signal is not None
    assert signal.action == SignalAction.BUY
    assert signal.strategy == "CTS_MVP_v2.3.1"


def test_wait_state_does_not_create_signal():
    adapter = CTSBacktestAdapter()

    signal = adapter.generate_signal(
        candle={
            "symbol": "ETHUSDT",
            "close": "3000",
            "timestamp": datetime(2026, 8, 13),
        },
        indicators={},
        state={
            "pullback_state": "WAIT_PULLBACK",
            "cooldown_ready": True,
            "dca_signal": True,
        },
    )

    assert signal is None


def test_cooldown_blocks_entry():
    adapter = CTSBacktestAdapter()

    signal = adapter.generate_signal(
        candle={
            "symbol": "BTCUSDT",
            "close": "60000",
            "timestamp": datetime(2026, 8, 13),
        },
        indicators={},
        state={
            "pullback_state": "LOCKED",
            "cooldown_ready": False,
            "dca_signal": True,
        },
    )

    assert signal is None
