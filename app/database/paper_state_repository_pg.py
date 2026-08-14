from __future__ import annotations

from typing import Any

from app.models.paper_fill_state import PaperFillState
from app.models.paper_order_state import PaperOrderState
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState


class PaperStateRepositoryPostgres:
    """PostgreSQL persistence adapter for paper trading state."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def save_runtime_state(self, state: PaperRuntimeState) -> None:
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

    async def load_runtime_state(self) -> PaperRuntimeState | None:
        row = await self._connection.fetchrow(
            "SELECT last_processed_timestamp, last_market_sequence, cash_balance FROM paper_runtime_state WHERE id=1"
        )
        if row is None:
            return None
        return PaperRuntimeState(
            last_processed_timestamp=row["last_processed_timestamp"],
            last_market_sequence=row["last_market_sequence"],
            cash_balance=row["cash_balance"],
        )

    async def save_order(self, order: PaperOrderState) -> None:
        await self._connection.execute(
            """
            INSERT INTO paper_orders(order_id, symbol, side, quantity, status, created_at)
            VALUES($1,$2,$3,$4,$5,$6)
            ON CONFLICT(order_id) DO UPDATE SET status=EXCLUDED.status
            """,
            order.order_id, order.symbol, order.side, order.quantity, order.status, order.created_at,
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
