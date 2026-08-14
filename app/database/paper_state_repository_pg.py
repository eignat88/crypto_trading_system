from __future__ import annotations

from datetime import datetime
from typing import Any

from app.models.paper_state import PaperRuntimeState


class PaperStateRepositoryPostgres:
    """PostgreSQL persistence adapter for paper trading runtime state.

    Storage operations are isolated from paper trading business logic.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    async def save_runtime_state(self, state: PaperRuntimeState) -> None:
        query = """
        INSERT INTO paper_runtime_state
        (
            id,
            last_processed_timestamp,
            last_market_sequence,
            cash_balance,
            updated_at
        )
        VALUES
        (1, $1, $2, $3, NOW())
        ON CONFLICT (id)
        DO UPDATE SET
            last_processed_timestamp = EXCLUDED.last_processed_timestamp,
            last_market_sequence = EXCLUDED.last_market_sequence,
            cash_balance = EXCLUDED.cash_balance,
            updated_at = NOW()
        """

        await self._connection.execute(
            query,
            state.last_processed_timestamp,
            state.last_market_sequence,
            state.cash_balance,
        )

    async def load_runtime_state(self) -> PaperRuntimeState | None:
        row = await self._connection.fetchrow(
            """
            SELECT
                last_processed_timestamp,
                last_market_sequence,
                cash_balance
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
