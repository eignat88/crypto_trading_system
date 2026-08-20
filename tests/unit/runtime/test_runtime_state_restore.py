from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.models.paper_fill_state import PaperFillState
from app.models.paper_state import PaperRuntimeState
from app.risk.risk_engine import RiskEngine
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository, MemoryRiskStore


@pytest.mark.asyncio
async def test_partial_restore_fails_closed() -> None:
    repository = MemoryCheckpointRepository()
    repository.state = PaperRuntimeState(datetime.now(UTC), 1, Decimal("4000"))
    repository.fills["fill"] = PaperFillState(
        "fill", "missing-order", "BTCUSDT", Decimal("0.1"), Decimal("60000"), datetime.now(UTC)
    )
    engine = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="incomplete"):
        await engine.restore_state()


def test_risk_state_survives_reconstruction() -> None:
    store = MemoryRiskStore()
    first = RiskEngine(state_store=store)
    first.update_pnl(Decimal("-50"), Decimal("-75"))
    first.update_equity(Decimal("10070"))
    first.update_equity(Decimal("10000"))
    first.set_emergency_stop(True, "operator")
    restored = RiskEngine(state_store=store)
    assert restored.daily_pnl == Decimal("-50")
    assert restored.weekly_pnl == Decimal("-75")
    assert restored.peak_equity == Decimal("10070")
    assert restored.current_equity == Decimal("10000")
    assert restored.is_emergency_stop is True
