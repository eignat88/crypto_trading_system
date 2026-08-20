from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.models.candle import Candle
from app.risk.risk_engine import RiskConfig, RiskEngine
from app.runtime.dependencies import RiskEngineAdapter

pytestmark = pytest.mark.asyncio


async def test_oversized_request_is_rejected_before_execution() -> None:
    engine = PaperExecutionEngine()
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    engine.on_candle(Candle("BTCUSDT", now, now + timedelta(hours=1), *(Decimal("100"),) * 5))
    risk = RiskEngine(RiskConfig(max_position_size=Decimal("0.10")))
    adapter = RiskEngineAdapter(risk, Decimal("1000"))
    approved = await adapter.validate_request(
        ExecutionRequest("BTCUSDT", OrderSide.BUY, Decimal("2")), engine
    )
    assert not approved
    assert engine.positions == {}
