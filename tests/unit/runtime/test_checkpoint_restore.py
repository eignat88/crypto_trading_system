from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository


@pytest.mark.asyncio
async def test_checkpoint_restores_cash_position_and_sequence() -> None:
    repository = MemoryCheckpointRepository()
    repository.state = PaperRuntimeState(datetime.now(UTC), 7, Decimal("4000"))
    repository.positions["BTCUSDT"] = PaperPositionState(
        "BTCUSDT", Decimal("0.1"), Decimal("60000")
    )
    restored = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    await restored.restore_state()
    assert (restored.last_sequence, restored.cash_balance) == (7, Decimal("4000"))
    assert restored.positions["BTCUSDT"].average_price == Decimal("60000")
