"""Runtime heartbeat snapshots and durable storage."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class RuntimeHealth:
    runtime_id: str
    status: str
    sequence: int
    heartbeat_time: datetime
    last_market_event_time: datetime | None
    created_at: datetime

    @property
    def uptime_seconds(self) -> float:
        return max(0.0, (self.heartbeat_time - self.created_at).total_seconds())

    @property
    def last_cycle(self) -> datetime:
        return self.heartbeat_time


class HeartbeatRepository(Protocol):
    def save(self, health: RuntimeHealth) -> object: ...


class PostgresHeartbeatRepository:
    """Persist heartbeats on a pool isolated from transactional runtime state.

    A dedicated pool is intentional: asyncpg connections allow one operation at
    a time, while shutdown checkpointing can overlap a monitoring write.
    """

    def __init__(self, pool: object) -> None:
        self.pool = pool

    async def save(self, health: RuntimeHealth) -> None:
        async with self.pool.acquire() as connection:  # type: ignore[attr-defined]
            await connection.execute(
                """INSERT INTO monitoring.runtime_health
                   (runtime_id, status, sequence, last_cycle_time,
                    last_market_event_time, uptime_seconds, created_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7)""",
                health.runtime_id,
                health.status,
                health.sequence,
                health.heartbeat_time,
                health.last_market_event_time,
                int(health.uptime_seconds),
                health.created_at,
            )


class Heartbeat:
    def __init__(
        self,
        runtime_id: str,
        repository: HeartbeatRepository | None = None,
        *,
        started_at: datetime | None = None,
    ) -> None:
        self.runtime_id = runtime_id
        self.repository = repository
        self.started_at = started_at or datetime.now(UTC)
        self.last_successful_cycle: datetime | None = None
        self.last_market_event_time: datetime | None = None
        self.sequence = 0
        self.state = "CREATED"

    async def beat(
        self,
        *,
        state: str,
        sequence: int | None = None,
        last_market_event_time: datetime | None = None,
        now: datetime | None = None,
    ) -> RuntimeHealth:
        timestamp = now or datetime.now(UTC)
        self.state = state.upper()
        if sequence is not None:
            if sequence < self.sequence:
                raise ValueError("heartbeat sequence cannot move backwards")
            self.sequence = sequence
        if last_market_event_time is not None:
            self.last_market_event_time = last_market_event_time
        self.last_successful_cycle = timestamp
        snapshot = RuntimeHealth(
            self.runtime_id,
            self.state,
            self.sequence,
            timestamp,
            self.last_market_event_time,
            self.started_at,
        )
        if self.repository is not None:
            result = self.repository.save(snapshot)
            if inspect.isawaitable(result):
                await result
        return snapshot
