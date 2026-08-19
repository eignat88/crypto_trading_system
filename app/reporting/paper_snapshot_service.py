"""Orchestration boundary for creating durable paper PnL checkpoints."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState
from app.reporting.paper_pnl import PaperPnLTracker, PnLRecord


class SnapshotRepository(Protocol):
    async def save_pnl_snapshot(self, snapshot: PaperPnLSnapshotState) -> None: ...


async def record_and_persist_snapshot(
    tracker: PaperPnLTracker,
    repository: SnapshotRepository,
    *,
    timestamp: datetime,
    sequence: int,
    realized_pnl: Decimal,
    unrealized_pnl: Decimal,
) -> PnLRecord:
    """Record then persist a checkpoint; persistence errors propagate to runtime."""
    record = tracker.record_snapshot(
        timestamp=timestamp,
        sequence=sequence,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
    )
    await repository.save_pnl_snapshot(tracker.snapshot_state(record))
    return record
