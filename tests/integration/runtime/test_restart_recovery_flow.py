from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState

pytestmark = pytest.mark.asyncio


class RecoveryRepository:
    state = PaperRuntimeState(datetime.now(UTC), 500, Decimal("900"))
    position = PaperPositionState("BTCUSDT", Decimal("0.1"), Decimal("800"))

    async def load_state(self):
        return self.state

    async def load_positions(self):
        return [self.position]


async def test_restart_recovery_is_idempotent() -> None:
    repository = RecoveryRepository()
    first = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    second = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    await first.restore_state()
    await second.restore_state()
    assert (first.last_sequence, first.cash_balance, first.positions) == (
        second.last_sequence,
        second.cash_balance,
        second.positions,
    )
