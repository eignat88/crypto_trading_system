from __future__ import annotations

from typing import Any

from app.exchange.paper_state_repository import PaperStateRepository
from app.models.paper_fill_state import PaperFillState
from app.models.paper_order_state import PaperOrderState
from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState


class PaperStateRepositoryPostgres(PaperStateRepository):
    """PostgreSQL persistence adapter for paper trading state."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def save_state(self, state: PaperRuntimeState) -> None:
        await self._connection.execute(
            """
            INSERT INTO paper_runtime_state
            (id, last_processed_timestamp, last_market_sequence, cash_balance, updated_at)
            VALUES (1, $1, $2, $3, NOW())
            ON CONFLICT (id) DO UPDATE SET
            last_processed_timestamp = EXCLUDED.last_processed_timestamp,
            last_market_sequence = EXCLUDED.last_market_sequence,
            cash_balance = EXCLUDED.cash_balance,
            updated_at = NOW()
            """,
            state.last_processed_timestamp,
            state.last_market_sequence,
            state.cash_balance,
        )

    async def load_state(self) -> PaperRuntimeState | None:
        row = await self._connection.fetchrow(
            """
            SELECT last_processed_timestamp, last_market_sequence, cash_balance
            FROM paper_runtime_state
            WHERE id = 1
            """
        )
        if row is None:
            return None
        return PaperRuntimeState(
            last_processed_timestamp=row["last_processed_timestamp"],
            last_market_sequence=row["last_market_sequence"],
            cash_balance=row["cash_balance"],
        )

    async def save_runtime_state(self, state: PaperRuntimeState) -> None:
        """Compatibility alias for the original adapter API."""
        await self.save_state(state)

    async def load_runtime_state(self) -> PaperRuntimeState | None:
        """Compatibility alias for the original adapter API."""
        return await self.load_state()

    async def save_pnl_snapshot(self, snapshot: PaperPnLSnapshotState) -> None:
        """Insert or replace a snapshot identified by its time and sequence."""
        snapshot.validate()
        await self._connection.execute(
            """
            INSERT INTO dds.paper_pnl_snapshots (
                snapshot_time, sequence_no, equity, realized_pnl, unrealized_pnl,
                total_pnl, fees_paid, slippage, cash_balance, position_value,
                drawdown, drawdown_pct
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            ON CONFLICT (snapshot_time, sequence_no) DO UPDATE SET
                equity = EXCLUDED.equity,
                realized_pnl = EXCLUDED.realized_pnl,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                total_pnl = EXCLUDED.total_pnl,
                fees_paid = EXCLUDED.fees_paid,
                slippage = EXCLUDED.slippage,
                cash_balance = EXCLUDED.cash_balance,
                position_value = EXCLUDED.position_value,
                drawdown = EXCLUDED.drawdown,
                drawdown_pct = EXCLUDED.drawdown_pct
            """,
            snapshot.timestamp,
            snapshot.sequence,
            snapshot.equity,
            snapshot.realized_pnl,
            snapshot.unrealized_pnl,
            snapshot.total_pnl,
            snapshot.fees_paid,
            snapshot.slippage,
            snapshot.cash_balance,
            snapshot.position_value,
            snapshot.drawdown,
            snapshot.drawdown_pct,
        )

    async def load_pnl_snapshots(self) -> list[PaperPnLSnapshotState]:
        """Return snapshots in deterministic equity-curve order."""
        rows = await self._connection.fetch(
            """
            SELECT
                snapshot_time, sequence_no, equity, realized_pnl, unrealized_pnl,
                total_pnl, fees_paid, slippage, cash_balance, position_value,
                drawdown, drawdown_pct
            FROM dds.paper_pnl_snapshots
            ORDER BY snapshot_time, sequence_no
            """
        )
        return [
            PaperPnLSnapshotState(
                timestamp=row["snapshot_time"],
                sequence=row["sequence_no"],
                equity=row["equity"],
                realized_pnl=row["realized_pnl"],
                unrealized_pnl=row["unrealized_pnl"],
                total_pnl=row["total_pnl"],
                fees_paid=row["fees_paid"],
                slippage=row["slippage"],
                cash_balance=row["cash_balance"],
                position_value=row["position_value"],
                drawdown=row["drawdown"],
                drawdown_pct=row["drawdown_pct"],
            )
            for row in rows
        ]

    async def save_order(self, order: PaperOrderState) -> None:
        await self._connection.execute(
            """
            INSERT INTO paper_orders(order_id, symbol, side, quantity, status, created_at)
            VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(order_id) DO UPDATE SET status=EXCLUDED.status
            """,
            order.order_id,
            order.symbol,
            order.side,
            order.quantity,
            order.status,
            order.created_at,
        )

    async def load_orders(self) -> list[PaperOrderState]:
        rows = await self._connection.fetch("SELECT * FROM paper_orders")
        return [PaperOrderState(**dict(row)) for row in rows]

    async def save_fill(self, fill: PaperFillState) -> None:
        await self._connection.execute(
            """
            INSERT INTO paper_fills(fill_id, order_id, symbol, quantity, price, executed_at)
            VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(fill_id) DO NOTHING
            """,
            fill.fill_id, fill.order_id, fill.symbol, fill.quantity, fill.price, fill.executed_at,
        )

    async def load_fills(self) -> list[PaperFillState]:
        rows = await self._connection.fetch("SELECT * FROM paper_fills")
        return [PaperFillState(**dict(row)) for row in rows]

    async def save_position(self, position: PaperPositionState) -> None:
        await self._connection.execute(
            """
            INSERT INTO paper_positions(symbol, quantity, average_price)
            VALUES($1,$2,$3)
            ON CONFLICT(symbol) DO UPDATE SET
            quantity=EXCLUDED.quantity,
            average_price=EXCLUDED.average_price
            """,
            position.symbol, position.quantity, position.average_price,
        )

    async def load_positions(self) -> list[PaperPositionState]:
        rows = await self._connection.fetch("SELECT * FROM paper_positions")
        return [PaperPositionState(**dict(row)) for row in rows]
