import pytest

from tests.helpers.runtime.paper_runtime_factory import make_runtime
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository
from tests.integration.runtime.test_restart_idempotency_e2e import market_event


@pytest.mark.asyncio
async def test_restored_sequence_ignores_same_and_processes_next() -> None:
    repository = MemoryCheckpointRepository()
    first, _, _, _ = make_runtime(repository, [market_event(100)])
    await first.run_async()
    second, engine, strategy, _ = make_runtime(repository, [market_event(100), market_event(101)])
    await second.run_async()
    assert strategy.signals == 1
    assert engine.last_sequence == 101
