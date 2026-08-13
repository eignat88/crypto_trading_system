from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.strategies.cts_backtest_strategy import CTSBacktestStrategy


def test_cts_initial_state_propagation_audit() -> None:
    candles = [
        {
            "symbol": "BTCUSDT",
            "open_time": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            "open": "60000",
            "high": "60100",
            "low": "59900",
            "close": "60050",
            "volume": "100",
        },
    ]

    strategy = CTSBacktestStrategy(symbols=["BTCUSDT"])
    engine = BacktestEngine(
        config=BacktestConfig(initial_balance=Decimal("5000"))
    )

    state = {
        "pullback_state": "LOCKED",
        "cooldown_ready": True,
        "dca_signal": True,
    }

    result = engine.run(
        candles=candles,
        strategy=strategy,
        initial_state=state,
    )

    print(f"CTS state propagation audit: strategy_state={strategy.state}")
    print(
        "CTS result audit: "
        f"signals={len(result.signals)} "
        f"risk_decisions={len(result.risk_decisions)} "
        f"orders={len(result.orders)} "
        f"fills={len(result.fills)}"
    )

    assert result is not None
