from datetime import datetime, timezone
from decimal import Decimal

from app.reporting.paper_pnl import PaperPnLTracker


def test_snapshot_converts_to_decimal_persistence_state() -> None:
    tracker = PaperPnLTracker(Decimal("10000"))
    timestamp = datetime(2026, 8, 19, tzinfo=timezone.utc)
    record = tracker.record_snapshot(timestamp, 7, realized_pnl=Decimal("25"),
                                     unrealized_pnl=Decimal("-5"))
    state = tracker.snapshot_state(record)
    assert state.snapshot_time == timestamp
    assert state.sequence == 7
    assert state.equity == Decimal("10020")
    assert state.realized_pnl == Decimal("25")
    assert state.unrealized_pnl == Decimal("-5")
