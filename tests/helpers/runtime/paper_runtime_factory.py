from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.execution.paper_trading_runtime import PaperTradingRuntime
from app.models.market_event import MarketEvent
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository


class EventSource:
    def __init__(self, events: Iterable[MarketEvent]) -> None:
        self.events = list(events)

    def stream(self):
        yield from self.events


class BuyOnceStrategy:
    def __init__(self) -> None:
        self.signals = 0

    async def on_candle(self, candle, engine):
        self.signals += 1
        return [ExecutionRequest(candle.symbol, OrderSide.BUY, Decimal("0.1"))]


class ApproveRisk:
    def __init__(self) -> None:
        self.decisions = 0

    async def validate_request(self, request, engine) -> bool:
        self.decisions += 1
        return True


def make_runtime(repository: MemoryCheckpointRepository, events: Iterable[MarketEvent]):
    engine = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    engine.cash_balance = Decimal("10000")
    strategy = BuyOnceStrategy()
    risk = ApproveRisk()
    runtime = PaperTradingRuntime(
        EventSource(events),  # type: ignore[arg-type]
        engine,
        strategy,
        risk,
        repository,  # type: ignore[arg-type]
    )
    return runtime, engine, strategy, risk
