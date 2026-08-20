import asyncio
from decimal import Decimal

from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository
from tests.integration.pipeline.support import build_pipeline, candle_event


def test_restart_restores_execution_and_ignores_checkpointed_sequence() -> None:
    asyncio.run(_test_restart_restores_execution_and_ignores_checkpointed_sequence())


async def _test_restart_restores_execution_and_ignores_checkpointed_sequence() -> None:
    repository = MemoryCheckpointRepository()
    before = build_pipeline(repository, required=200)
    for sequence in range(1, 211):
        await before.pipeline.process_market_event(candle_event(sequence))
    position = before.engine.positions["BTCUSDT"]
    timestamp = candle_event(210).timestamp
    await repository.save_pnl_snapshot(
        PaperPnLSnapshotState(
            timestamp=timestamp,
            sequence=210,
            equity=Decimal("10020"),
            realized_pnl=Decimal("20"),
            unrealized_pnl=Decimal("0"),
            total_pnl=Decimal("20"),
            fees_paid=Decimal("0"),
            slippage=Decimal("0"),
            cash_balance=before.engine.cash_balance,
            position_value=position.quantity * position.average_price,
            drawdown=Decimal("0"),
            drawdown_pct=Decimal("0"),
        )
    )

    after = build_pipeline(repository, required=200)
    await after.engine.restore_state()
    after.pipeline.restore_checkpoint({"BTCUSDT": after.engine.last_sequence})
    restored_pnl = (await repository.load_pnl_snapshots())[-1]
    replay = await after.pipeline.process_market_event(candle_event(210))

    assert replay.status.value == "IGNORED"
    assert after.engine.last_sequence == 210
    assert after.engine.positions["BTCUSDT"].quantity == position.quantity
    assert restored_pnl.total_pnl == Decimal("20")
    assert len(after.engine.orders) == 1
    assert len(after.engine.fills) == 1
