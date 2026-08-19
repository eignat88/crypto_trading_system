import asyncio
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import asyncpg
import pytest

from app.database.paper_state_repository_pg import PaperStateRepositoryPostgres
from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
MIGRATION = Path(__file__).parents[2] / "sql" / "022_create_paper_pnl_snapshot.sql"


def snapshot() -> PaperPnLSnapshotState:
    return PaperPnLSnapshotState(
        timestamp=datetime(2026, 8, 19, 12, tzinfo=UTC),
        sequence=42,
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


async def connect() -> asyncpg.Connection:
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return await asyncpg.connect(DATABASE_URL)


async def prepare_database() -> asyncpg.Connection:
    connection = await connect()
    await connection.execute(MIGRATION.read_text(encoding="utf-8"))
    await connection.execute("TRUNCATE dds.paper_pnl_snapshots")
    return connection


def test_snapshot_survives_repository_recreation() -> None:
    async def scenario() -> None:
        connection = await prepare_database()
        state = snapshot()
        try:
            await PaperStateRepositoryPostgres(connection).save_pnl_snapshot(state)
        finally:
            await connection.close()

        restarted_connection = await connect()
        try:
            restarted_repository = PaperStateRepositoryPostgres(restarted_connection)

            assert await restarted_repository.load_pnl_snapshots() == [state]
        finally:
            await restarted_connection.execute("TRUNCATE dds.paper_pnl_snapshots")
            await restarted_connection.close()

    asyncio.run(scenario())


def test_saving_same_snapshot_twice_does_not_duplicate() -> None:
    async def scenario() -> None:
        connection = await prepare_database()
        try:
            repository = PaperStateRepositoryPostgres(connection)
            state = snapshot()

            await repository.save_pnl_snapshot(state)
            await repository.save_pnl_snapshot(state)

            count = await connection.fetchval("SELECT count(*) FROM dds.paper_pnl_snapshots")
            assert count == 1
        finally:
            await connection.execute("TRUNCATE dds.paper_pnl_snapshots")
            await connection.close()

    asyncio.run(scenario())
