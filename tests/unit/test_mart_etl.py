import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.reporting.mart_etl import MartETL
from app.reporting.paper_metrics import PaperMetricsCollector
from app.reporting.paper_pnl import PaperPnLTracker


class _ScalarResult:
    def scalar_one(self) -> int:
        return 1


class RecordingSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def execute(
        self, statement: Any, parameters: dict[str, Any] | None = None
    ) -> _ScalarResult:
        self.calls.append((str(statement), parameters))
        return _ScalarResult()


def test_load_aggregates_and_uses_upserts() -> None:
    tracker = PaperPnLTracker(initial_capital=Decimal("1000"))
    collector = PaperMetricsCollector(tracker)
    start = datetime(2026, 8, 1, 10, tzinfo=UTC)
    collector.record_trade(start, "BTCUSDT", "BUY", Decimal("1"), Decimal("100"), Decimal("1"))
    collector.snapshot_equity(start, sequence=1, realized_pnl=Decimal("0"))
    collector.record_trade(
        start + timedelta(hours=1), "BTCUSDT", "SELL", Decimal("1"), Decimal("120"), Decimal("1")
    )
    tracker._fees_paid = Decimal("2")
    collector.snapshot_equity(start + timedelta(hours=1), sequence=2, realized_pnl=Decimal("20"))
    session = RecordingSession()

    result = asyncio.run(MartETL(session, tracker, collector).load())  # type: ignore[arg-type]

    assert result.daily_performance == 1
    assert result.trade_statistics == 1
    assert result.drawdown_history == 2
    assert result.monthly_returns == 1
    writes = [sql for sql, _ in session.calls[1:]]
    assert sum("ON CONFLICT" in sql for sql in writes) == 3
    assert sum("MERGE INTO mart.drawdown_history" in sql for sql in writes) == 2
    daily = session.calls[1][1]
    assert daily is not None
    assert daily["winning_trades"] == 1
    assert daily["open_positions"] == 1


def test_empty_reporting_state_is_a_noop() -> None:
    tracker = PaperPnLTracker()
    session = RecordingSession()

    result = asyncio.run(
        MartETL(session, tracker, PaperMetricsCollector(tracker)).load()  # type: ignore[arg-type]
    )

    assert result.daily_performance == 0
    assert result.trade_statistics == 0
    assert result.drawdown_history == 0
    assert result.monthly_returns == 0
    assert len(session.calls) == 1


def test_rejects_oversell_in_collected_trade_history() -> None:
    tracker = PaperPnLTracker()
    collector = PaperMetricsCollector(tracker)
    collector.record_trade(
        datetime(2026, 8, 1, tzinfo=UTC),
        "BTCUSDT",
        "SELL",
        Decimal("1"),
        Decimal("100"),
    )
    etl = MartETL(RecordingSession(), tracker, collector)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="exceeds collected position"):
        etl._realized_trade_pnl(collector.trade_events)
