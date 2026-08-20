from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository


@pytest.mark.asyncio
async def test_pnl_snapshot_survives_restart() -> None:
    repository = MemoryCheckpointRepository()
    snapshot = PaperPnLSnapshotState(
        datetime.now(UTC), 1, Decimal("10070"), Decimal("50"), Decimal("20"),
        Decimal("70"), Decimal("0"), Decimal("0"), Decimal("4000"),
        Decimal("6070"), Decimal("0"), Decimal("0"),
    )
    await repository.save_pnl_snapshot(snapshot)
    assert await repository.load_pnl_snapshots() == [snapshot]
