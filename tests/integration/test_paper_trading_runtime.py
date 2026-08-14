from decimal import Decimal
from datetime import datetime, timezone

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.models.candle import Candle
from app.runtime.paper_trading_runtime import PaperTradingRuntime


def test_runtime_processes_market_data_to_execution_engine():
    candles = [
        Candle(
            symbol="BTCUSDT",
            open_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
            close_time=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("1"),
        )
    ]

    runtime = PaperTradingRuntime(
        market_data=PaperMarketData(candles),
        execution_engine=PaperExecutionEngine(),
    )

    events = list(runtime.run())

    assert len(events) == 1
    assert runtime.status.processed_events == 1
    assert runtime.execution_engine.last_candle is not None
    assert runtime.execution_engine.last_candle.close == Decimal("105")
