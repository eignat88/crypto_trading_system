"""PostgreSQL availability and checkpoint health checks."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import monotonic


class DatabaseHealthStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class DatabaseHealthResult:
    database: str
    status: DatabaseHealthStatus
    latency_ms: float
    checkpoint_available: bool
    trading_enabled: bool
    error: str | None = None


class DatabaseHealthMonitor:
    def __init__(
        self,
        connection_check: Callable[[], object],
        checkpoint_check: Callable[[], object] | None = None,
        *,
        latency_warning_ms: float = 500.0,
    ) -> None:
        self.connection_check = connection_check
        self.checkpoint_check = checkpoint_check
        self.latency_warning_ms = latency_warning_ms
        self.transaction_errors = 0

    def record_transaction_error(self) -> None:
        self.transaction_errors += 1

    async def check(self) -> DatabaseHealthResult:
        started = monotonic()
        try:
            connected = self.connection_check()
            if inspect.isawaitable(connected):
                connected = await connected
            if not connected:
                raise ConnectionError("database connection check failed")
            checkpoint_result: object = True
            if self.checkpoint_check is not None:
                checkpoint_result = self.checkpoint_check()
                if inspect.isawaitable(checkpoint_result):
                    checkpoint_result = await checkpoint_result
            checkpoint = bool(checkpoint_result)
            latency = (monotonic() - started) * 1000
            degraded = latency >= self.latency_warning_ms or not checkpoint
            status = DatabaseHealthStatus.DEGRADED if degraded else DatabaseHealthStatus.OK
            return DatabaseHealthResult("postgres", status, latency, checkpoint, not degraded)
        except Exception as exc:
            latency = (monotonic() - started) * 1000
            self.record_transaction_error()
            return DatabaseHealthResult(
                "postgres", DatabaseHealthStatus.UNAVAILABLE, latency, False, False, str(exc)
            )
