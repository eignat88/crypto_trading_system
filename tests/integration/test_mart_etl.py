from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database.connection import async_session_factory
from app.reporting.mart_etl import MartETL
from app.reporting.paper_metrics import PaperMetricsCollector
from app.reporting.paper_pnl import PaperPnLTracker


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mart_load_is_idempotent() -> None:
    tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
    collector = PaperMetricsCollector(tracker)
    timestamp = datetime(2099, 1, 15, 12, tzinfo=UTC)
    collector.snapshot_equity(timestamp, sequence=1, realized_pnl=Decimal("25"))

    async with async_session_factory() as session:
        transaction = await session.begin()
        try:
            # Integration databases may have been provisioned from 003 before the
            # drawdown idempotency key was added. Apply the same idempotent schema
            # upgrade that production receives when migrations are rerun.
            await session.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "uq_mart_drawdown_history_timestamp "
                    "ON mart.drawdown_history (timestamp)"
                )
            )
            etl = MartETL(session, tracker, collector, "mart-etl-test")
            await etl.load()
            await etl.load()
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM mart.daily_performance "
                    "WHERE report_date=:day AND exchange_name=:exchange"
                ),
                {"day": timestamp.date(), "exchange": "mart-etl-test"},
            )
            assert count == 1
        finally:
            await transaction.rollback()
