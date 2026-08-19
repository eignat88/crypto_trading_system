import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

from app.database.paper_state_repository_pg import PaperStateRepositoryPostgres
from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState


def snapshot(sequence: int = 1) -> PaperPnLSnapshotState:
    return PaperPnLSnapshotState(
        timestamp=datetime(2026, 8, 19, tzinfo=UTC) + timedelta(hours=sequence),
        sequence=sequence,
        equity=Decimal("10125"),
        realized_pnl=Decimal("100"),
        unrealized_pnl=Decimal("25"),
        total_pnl=Decimal("125"),
        fees_paid=Decimal("2.5"),
        slippage=Decimal("0.5"),
        cash_balance=Decimal("9000"),
        position_value=Decimal("1125"),
        drawdown=Decimal("10"),
        drawdown_pct=Decimal("0.0987"),
    )


def test_save_pnl_snapshot_uses_composite_key_upsert() -> None:
    connection = AsyncMock()
    repository = PaperStateRepositoryPostgres(connection)
    state = snapshot()

    asyncio.run(repository.save_pnl_snapshot(state))

    query, *parameters = connection.execute.await_args.args
    assert "ON CONFLICT (snapshot_time, sequence_no) DO UPDATE" in query
    assert parameters == [
        state.timestamp,
        state.sequence,
        state.equity,
        state.realized_pnl,
        state.unrealized_pnl,
        state.total_pnl,
        state.fees_paid,
        state.slippage,
        state.cash_balance,
        state.position_value,
        state.drawdown,
        state.drawdown_pct,
    ]


def test_load_pnl_snapshots_maps_rows_in_requested_order() -> None:
    states = [snapshot(1), snapshot(2)]
    connection = AsyncMock()
    connection.fetch.return_value = [
        {
            "snapshot_time": state.timestamp,
            "sequence_no": state.sequence,
            "equity": state.equity,
            "realized_pnl": state.realized_pnl,
            "unrealized_pnl": state.unrealized_pnl,
            "total_pnl": state.total_pnl,
            "fees_paid": state.fees_paid,
            "slippage": state.slippage,
            "cash_balance": state.cash_balance,
            "position_value": state.position_value,
            "drawdown": state.drawdown,
            "drawdown_pct": state.drawdown_pct,
        }
        for state in states
    ]
    repository = PaperStateRepositoryPostgres(connection)

    loaded = asyncio.run(repository.load_pnl_snapshots())

    assert loaded == states
    query = connection.fetch.await_args.args[0]
    assert "ORDER BY snapshot_time, sequence_no" in query
