"""PostgreSQL round-trip and idempotency for paper PnL snapshots."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration


def test_snapshot_upsert_and_chronological_load() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    migration = Path(__file__).parents[2] / "sql/022_create_paper_pnl_snapshot.sql"
    with psycopg.connect(database_url) as connection:
        connection.execute(migration.read_text())
        connection.execute("TRUNCATE dds.paper_pnl_snapshot")
        base = datetime(2026, 8, 19, tzinfo=UTC)
        values = (base, 1, *(Decimal("1") for _ in range(10)))
        later = (base + timedelta(minutes=1), 2, *(Decimal("2") for _ in range(10)))
        query = """
            INSERT INTO dds.paper_pnl_snapshot
            (snapshot_time, sequence, equity, realized_pnl, unrealized_pnl, total_pnl,
             fees_paid, slippage, cash_balance, position_value, drawdown, drawdown_pct)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (snapshot_time, sequence) DO UPDATE SET equity=EXCLUDED.equity
        """
        connection.execute(query, values)
        connection.execute(query, later)
        connection.execute(query, later)
        rows = connection.execute(
            "SELECT snapshot_time, sequence, equity FROM dds.paper_pnl_snapshot "
            "ORDER BY snapshot_time, sequence"
        ).fetchall()
        assert len(rows) == 2
        assert [row[1] for row in rows] == [1, 2]
        assert [row[2] for row in rows] == [Decimal("1"), Decimal("2")]
