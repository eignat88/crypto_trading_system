"""Regression coverage for heartbeat/checkpoint connection isolation."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.execution.paper_trading_runtime import PaperTradingRuntime
from app.monitoring.heartbeat import Heartbeat, PostgresHeartbeatRepository
from app.risk.risk_engine import RiskConfig, RiskEngine
from app.runtime.dependencies import PaperDependencies
from app.runtime.paper_application import PaperApplication


class MonitoringConnection:
    def __init__(self) -> None:
        self.executed = asyncio.Event()

    async def execute(self, query: str, *values: object) -> None:
        assert "monitoring.runtime_health" in query
        assert "last_cycle_time" in query
        self.executed.set()


class AcquireContext:
    def __init__(self, connection: MonitoringConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> MonitoringConnection:
        return self.connection

    async def __aexit__(self, *args: object) -> None:
        return None


class MonitoringPool:
    def __init__(self) -> None:
        self.connection = MonitoringConnection()
        self.acquisitions = 0

    def acquire(self) -> AcquireContext:
        self.acquisitions += 1
        return AcquireContext(self.connection)


class StateRepository:
    def __init__(self) -> None:
        self.checkpoints = 0

    async def load_state(self):
        return None

    async def load_positions(self):
        return []

    async def save_state(self, state) -> None:
        self.checkpoints += 1

    async def load_pnl_snapshots(self):
        return []


def test_heartbeat_saved_then_shutdown_checkpoint_uses_isolated_resource() -> None:
    asyncio.run(_heartbeat_saved_then_shutdown_checkpoint_uses_isolated_resource())


async def _heartbeat_saved_then_shutdown_checkpoint_uses_isolated_resource() -> None:
    pool = MonitoringPool()
    heartbeat = Heartbeat(
        "paper-runtime-test",
        PostgresHeartbeatRepository(pool),
        started_at=datetime(2026, 8, 20, tzinfo=UTC),
    )
    repository = StateRepository()
    engine = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    runtime = PaperTradingRuntime(
        PaperMarketData([]),
        engine,
        state_repository=repository,  # type: ignore[arg-type]
        heartbeat=heartbeat,
    )

    async def healthy() -> bool:
        return True

    async def warmup(symbols: list[str], required: int) -> dict[str, int]:
        return {symbol: required for symbol in symbols}

    async def close() -> None:
        return None

    risk = RiskEngine(RiskConfig())
    dependencies = PaperDependencies(
        runtime=runtime,
        repository=repository,  # type: ignore[arg-type]
        risk_engine=risk,
        database_check=healthy,
        migration_check=healthy,
        warmup=warmup,
        close=close,
        trading_mode="paper",
        exchange="demo",
        symbols=["BTCUSDT"],
        initial_capital=Decimal("1000"),
        risk_config=risk.config,
        heartbeat=heartbeat,
    )

    application = PaperApplication(dependencies)
    await application.start()
    assert pool.connection.executed.is_set()
    await application.stop()

    assert repository.checkpoints >= 1
    assert pool.acquisitions == 2  # RUNNING and STOPPED heartbeat rows


def test_canonical_migration_creates_monitoring_runtime_health() -> None:
    migration = Path("database/migrations/050_runtime_health.sql").read_text()
    assert "CREATE SCHEMA IF NOT EXISTS monitoring" in migration
    assert "CREATE TABLE IF NOT EXISTS monitoring.runtime_health" in migration
    assert "last_cycle_time TIMESTAMPTZ" in migration
    assert "uptime_seconds BIGINT" in migration
