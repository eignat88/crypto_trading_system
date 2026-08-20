from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.execution.paper_trading_runtime import PaperTradingRuntime
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState

pytestmark = pytest.mark.asyncio


class Repository:
    state = PaperRuntimeState(datetime.now(UTC), 500, Decimal("900"))

    async def load_state(self):
        return self.state

    async def load_positions(self):
        return [PaperPositionState("BTCUSDT", Decimal("0.1"), Decimal("800"))]


async def test_restore_preserves_sequence_cash_and_position() -> None:
    repository = Repository()
    engine = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    runtime = PaperTradingRuntime(PaperMarketData([]), engine, state_repository=repository)  # type: ignore[arg-type]
    state = await runtime.restore_state()
    assert state is not None and state.last_market_sequence == 500
    assert engine.cash_balance == Decimal("900")
    assert engine.positions["BTCUSDT"].quantity == Decimal("0.1")
