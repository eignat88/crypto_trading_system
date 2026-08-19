from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState
from app.reporting.paper_pnl import PaperPnLTracker


def _state(index: int, equity: str, drawdown: str) -> PaperPnLSnapshotState:
    value = Decimal(equity)
    return PaperPnLSnapshotState(
        datetime(2026, 8, 19, tzinfo=timezone.utc) + timedelta(minutes=index), index,
        value, value - Decimal("10000"), Decimal("0"), value - Decimal("10000"),
        Decimal(index), Decimal(index) / 10, Decimal("10000"), Decimal("0"),
        Decimal(drawdown), Decimal(drawdown) / Decimal("110"),
    )


def test_restore_is_ordered_idempotent_and_restores_peak_and_totals() -> None:
    snapshots = [_state(3, "10500", "500"), _state(0, "10000", "0"),
                 _state(2, "11000", "0"), _state(1, "10500", "0")]
    tracker = PaperPnLTracker()
    tracker.restore_snapshots(snapshots)
    tracker.restore_snapshots(snapshots)
    assert [point.sequence for point in tracker.equity_curve] == [0, 1, 2, 3]
    assert len(tracker.pnl_records) == 4
    assert tracker.current_equity == Decimal("10500")
    assert tracker.current_drawdown == Decimal("500")
    assert tracker.pnl_records[-1].fees_paid == Decimal("3")
    assert tracker.pnl_records[-1].slippage == Decimal("0.3")


def test_empty_restore_preserves_normal_initial_state() -> None:
    tracker = PaperPnLTracker(Decimal("123"))
    tracker.restore_snapshots([])
    assert tracker.current_equity == Decimal("123")
    assert tracker.equity_curve == []
