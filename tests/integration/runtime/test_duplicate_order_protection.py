from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository


@pytest.mark.asyncio
async def test_restored_order_is_not_submitted_twice() -> None:
    repository = MemoryCheckpointRepository()
    request = ExecutionRequest("BTCUSDT", OrderSide.BUY, Decimal("0.1"))
    first = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    first.execute(request, Decimal("60000"), client_order_id="paper:1:0:BTCUSDT:BUY")
    await first.flush()
    second = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    await second.restore_state()
    second.execute(request, Decimal("60000"), client_order_id="paper:1:0:BTCUSDT:BUY")
    assert len(repository.orders) == len(repository.fills) == 1
    assert second.positions["BTCUSDT"].quantity == Decimal("0.1")
