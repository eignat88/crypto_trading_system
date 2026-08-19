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
            drawdown_count = await session.scalar(
                text("SELECT count(*) FROM mart.drawdown_history WHERE timestamp=:timestamp"),
                {"timestamp": timestamp},
            )
            assert drawdown_count == 1
        finally:
            await transaction.rollback()
