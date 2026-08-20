import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.execution.paper_trading_runtime import PaperTradingRuntime
from app.models.candle import Candle
from app.models.market_event import MarketEvent
from app.monitoring.heartbeat import Heartbeat


def event(sequence: int) -> MarketEvent:
    opened = datetime(2026, 8, 20, 10, tzinfo=UTC) + timedelta(minutes=sequence)
    return MarketEvent(
        Candle(
            "BTCUSDT", opened, opened + timedelta(minutes=1),
            *(Decimal("60000"),) * 4, Decimal("1"),
        ),
        sequence,
    )


def test_sequence_guard_accepts_only_strictly_new_events() -> None:
    engine = PaperExecutionEngine()
    engine._last_sequence = 100
    engine.on_market_event(event(100))
    assert engine.last_sequence == 100
    engine.on_market_event(event(101))
    assert engine.last_sequence == 101


def test_runtime_heartbeat_uses_processed_not_checkpoint_sequence() -> None:
    heartbeat = Heartbeat("runtime-test")
    runtime = PaperTradingRuntime(
        PaperMarketData([]),
        PaperExecutionEngine(),
        heartbeat=heartbeat,
        checkpoint_interval=2,
    )

    asyncio.run(runtime._process_candle(event(101)))

    assert runtime.last_processed_sequence == 101
    assert runtime.last_checkpoint_sequence == 0
    assert heartbeat.sequence == 101
