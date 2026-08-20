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
    def __init__(self, connection: object) -> None:
        self.connection = connection

    async def save(self, health: RuntimeHealth) -> None:
        await self.connection.execute(  # type: ignore[attr-defined]
            """INSERT INTO monitoring.runtime_health
               (runtime_id, status, sequence, heartbeat_time,
                last_market_event_time, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT (runtime_id) DO UPDATE SET
                 status = EXCLUDED.status, sequence = EXCLUDED.sequence,
                 heartbeat_time = EXCLUDED.heartbeat_time,
                 last_market_event_time = EXCLUDED.last_market_event_time""",
            health.runtime_id,
            health.status,
            health.sequence,
            health.heartbeat_time,
            health.last_market_event_time,
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
