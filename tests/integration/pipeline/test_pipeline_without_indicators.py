import asyncio

from app.pipeline import PipelineState, PipelineStatus
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository
from tests.integration.pipeline.support import build_pipeline, candle_event


def test_fifty_candles_cannot_cross_ema200_trading_gate() -> None:
    asyncio.run(_test_fifty_candles_cannot_cross_ema200_trading_gate())


async def _test_fifty_candles_cannot_cross_ema200_trading_gate() -> None:
    components = build_pipeline(MemoryCheckpointRepository(), required=200)
    result = None
    for sequence in range(1, 51):
        result = await components.pipeline.process_market_event(candle_event(sequence))

    assert result is not None and result.status is PipelineStatus.WARMUP
    assert components.pipeline.pipeline_state is PipelineState.WARMUP
    assert not components.pipeline.is_trading_ready()
    assert components.strategy.evaluations == 0
    assert components.risk.decisions == 0
    assert components.execution.results == []
