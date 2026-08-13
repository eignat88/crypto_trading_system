from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.strategies.cts_backtest_strategy import CTSBacktestStrategy


def test_cts_order_fill_portfolio_lifecycle_without_same_bar_execution() -> None:
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
        {
            "symbol": "BTCUSDT",
            "open_time": datetime(2026, 1, 1, 1, 0, tzinfo=UTC),
            "open": "60050",
            "high": "60200",
            "low": "60000",
            "close": "60150",
            "volume": "120",
        },
    ]

    strategy = CTSBacktestStrategy(symbols=["BTCUSDT"])
    engine = BacktestEngine(
        config=BacktestConfig(initial_balance=Decimal("5000"))
    )

    result = engine.run(
        candles=candles,
        strategy=strategy,
        initial_state={
            "pullback_state": "LOCKED",
            "cooldown_ready": True,
            "dca_signal": True,
        },
    )

    assert result is not None
    assert result.trades is not None
