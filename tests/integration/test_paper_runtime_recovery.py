from decimal import Decimal
from datetime import datetime, timezone

import pytest

from app.exchange.paper_execution_engine import (
    ExecutionRequest,
    OrderSide,
    PaperExecutionEngine,
)
from app.exchange.paper_market_data import PaperMarketData
from app.models.candle import Candle
from app.models.paper_state import PaperRuntimeState
from app.models.paper_position_state import PaperPositionState
from app.runtime.paper_trading_runtime import PaperTradingRuntime


class InMemoryPaperRepository:
    def __init__(self) -> None:
        self.state = None
        self.positions = []
        self.orders = []
        self.fills = []

    async def save_state(self, state: PaperRuntimeState) -> None:
        self.state = state

    async def load_state(self):
        return self.state

    async def save_position(self, position: PaperPositionState) -> None:
        self.positions = [position]

    async def load_positions(self):
        return self.positions

    async def save_order(self, order) -> None:
        self.orders.append(order)

    async def save_fill(self, fill) -> None:
        self.fills.append(fill)


@pytest.mark.asyncio
async def test_runtime_restores_position_after_restart_and_continues_execution():
    candle = Candle(
        symbol="BTCUSDT",
        open_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        close_time=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1"),
    )

    repository = InMemoryPaperRepository()

    engine = PaperExecutionEngine(state_repository=repository)
    runtime = PaperTradingRuntime(
        market_data=PaperMarketData([candle]),
        execution_engine=engine,
    )

    list(runtime.run())
    engine.execute(
        ExecutionRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        )
    )

    restored_engine = PaperExecutionEngine(state_repository=repository)
    restored_runtime = PaperTradingRuntime(
        market_data=PaperMarketData([candle]),
        execution_engine=restored_engine,
    )

    await restored_runtime.restore_state()

    position = restored_engine.positions["BTCUSDT"]

    assert position.quantity == Decimal("0.1")
    assert position.average_price == Decimal("105")
    assert restored_runtime.status.restored is True

    fills_before = len(repository.fills)

    list(restored_runtime.run())

    assert len(repository.fills) == fills_before
    assert restored_engine.last_candle is not None
