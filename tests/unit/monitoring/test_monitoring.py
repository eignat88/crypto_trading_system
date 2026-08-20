import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.monitoring.database_health import DatabaseHealthMonitor, DatabaseHealthStatus
from app.monitoring.heartbeat import Heartbeat
from app.monitoring.market_health import MarketHealthMonitor, MarketHealthStatus
from app.monitoring.pipeline_health import PipelineHealthMonitor, PipelineHealthStatus


def test_heartbeat_is_monotonic_and_persisted():
    saved = []

    class Repository:
        def save(self, value):
            saved.append(value)

    start = datetime(2026, 8, 20, tzinfo=UTC)
    heartbeat = Heartbeat("runtime-1", Repository(), started_at=start)
    result = asyncio.run(
        heartbeat.beat(state="running", sequence=4, now=start + timedelta(seconds=9))
    )
    assert result.uptime_seconds == 9
    assert result.status == "RUNNING"
    assert saved == [result]
    with pytest.raises(ValueError, match="backwards"):
        asyncio.run(heartbeat.beat(state="RUNNING", sequence=3))


def test_market_health_thresholds_and_gaps():
    now = datetime(2026, 8, 20, 12, tzinfo=UTC)
    monitor = MarketHealthMonitor()
    ok = monitor.check("BTCUSDT", "1h", now - timedelta(minutes=4), received_at=now)
    warning = monitor.check("ETHUSDT", "1h", now - timedelta(minutes=5), received_at=now)
    assert ok.status is MarketHealthStatus.OK
    assert warning.status is MarketHealthStatus.WARNING
    result = monitor.check("XRPUSDT", "1h", now - timedelta(minutes=16), received_at=now)
    assert result.status is MarketHealthStatus.CRITICAL
    assert not result.trading_enabled


def test_missing_indicator_degrades_and_execution_failure_stops():
    monitor = PipelineHealthMonitor()
    degraded = monitor.check(indicators={}, required_indicators=["EMA200"])
    assert degraded.status is PipelineHealthStatus.DEGRADED
    assert not degraded.trading_enabled
    failed = monitor.check(execution_error=RuntimeError("execution failed"))
    assert failed.status is PipelineHealthStatus.FAILED
    assert failed.emergency_stop


def test_database_failure_is_fail_closed():
    async def unavailable():
        raise ConnectionError("down")

    result = asyncio.run(DatabaseHealthMonitor(unavailable).check())
    assert result.status is DatabaseHealthStatus.UNAVAILABLE
    assert not result.trading_enabled
