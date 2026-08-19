from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState


def snapshot(**overrides: object) -> PaperPnLSnapshotState:
    values = {
        "timestamp": datetime(2026, 8, 19, tzinfo=UTC),
        "sequence": 7,
        "equity": Decimal("10125"),
        "realized_pnl": Decimal("100"),
        "unrealized_pnl": Decimal("25"),
        "total_pnl": Decimal("125"),
        "fees_paid": Decimal("2.5"),
        "slippage": Decimal("0.5"),
        "cash_balance": Decimal("9000"),
        "position_value": Decimal("1125"),
        "drawdown": Decimal("10"),
        "drawdown_pct": Decimal("0.0987"),
    }
    values.update(overrides)
    return PaperPnLSnapshotState(**values)  # type: ignore[arg-type]


def test_valid_snapshot_state() -> None:
    state = snapshot()

    state.validate()

    assert state.sequence == 7
    assert state.total_pnl == Decimal("125")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("sequence", -1, "Snapshot sequence cannot be negative"),
        ("equity", Decimal("-1"), "Snapshot equity cannot be negative"),
        ("fees_paid", Decimal("-1"), "Snapshot fees cannot be negative"),
        ("drawdown", Decimal("-1"), "Snapshot drawdown cannot be negative"),
        ("drawdown_pct", Decimal("-1"), "Snapshot drawdown cannot be negative"),
    ],
)
def test_invalid_snapshot_state(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        snapshot(**{field: value}).validate()
