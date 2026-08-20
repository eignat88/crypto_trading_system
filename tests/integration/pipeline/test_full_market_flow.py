import asyncio

from app.pipeline import PipelineStatus
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository
from tests.integration.pipeline.support import build_pipeline, candle_event


def test_closed_candle_runs_the_complete_managed_flow() -> None:
    asyncio.run(_test_closed_candle_runs_the_complete_managed_flow())


async def _test_closed_candle_runs_the_complete_managed_flow() -> None:
    components = build_pipeline(MemoryCheckpointRepository(), required=200)
    result = None
    for sequence in range(1, 211):
        result = await components.pipeline.process_market_event(candle_event(sequence))
    await components.pipeline.stop()

    assert result is not None and result.status is PipelineStatus.PROCESSED
    assert len(components.raw.events) == 210
    assert len(components.dds.candles) == 210
    assert len(components.indicators.rows) == 210
    assert len(components.regimes.rows) == 210
    assert components.strategy.evaluations > 0
    assert components.risk.decisions == 1
    assert len(components.execution.results) == 1
    assert len(components.engine.orders) == 1
    assert len(components.engine.fills) == 1
    assert components.persistence.checkpoints["BTCUSDT"] == 210
    assert components.mart.refreshes > 0
