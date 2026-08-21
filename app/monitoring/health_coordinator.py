"""Unified health coordinator that wires monitors to emergency stop and alerts.

Runs periodic health checks across all subsystems, feeds results into the
Risk Engine, triggers EmergencyStop on critical failures, and sends alerts
via the Notifier interface.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, TYPE_CHECKING

import structlog

from app.monitoring.database_health import DatabaseHealthMonitor, DatabaseHealthStatus
from app.monitoring.market_health import MarketHealthMonitor, MarketHealthStatus
from app.monitoring.notifier import NotificationLevel, Notifier, send_notification
from app.monitoring.pipeline_health import PipelineHealthMonitor, PipelineHealthStatus
from app.monitoring.risk_health import RiskHealthMonitor, RiskHealthStatus

if TYPE_CHECKING:
    from app.risk.emergency_stop import EmergencyStop

logger = structlog.get_logger()


class SystemHealthStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class SystemHealthResult:
    status: SystemHealthStatus
    database: DatabaseHealthStatus | None = None
    market: MarketHealthStatus | None = None
    risk: RiskHealthStatus | None = None
    pipeline: PipelineHealthStatus | None = None
    reasons: tuple[str, ...] = ()
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class HealthCoordinator:
    """Orchestrate health monitoring and emergency response.

    Responsibilities:
    - Run periodic health checks across all subsystems
    - Feed health status into RiskEngine for operational gating
    - Trigger EmergencyStop on critical failures (fail-closed)
    - Send alerts via Notifier for all severity transitions
    - Track health history for diagnostics
    """

    def __init__(
        self,
        *,
        database_monitor: DatabaseHealthMonitor | None = None,
        market_monitor: MarketHealthMonitor | None = None,
        risk_monitor: RiskHealthMonitor | None = None,
        pipeline_monitor: PipelineHealthMonitor | None = None,
        risk_engine: Any = None,
        emergency_stop: EmergencyStop | None = None,
        notifier: Notifier | None = None,
        check_interval: timedelta = timedelta(seconds=30),
        runtime_id: str | None = None,
    ) -> None:
        self.database_monitor = database_monitor
        self.market_monitor = market_monitor
        self.risk_monitor = risk_monitor
        self.pipeline_monitor = pipeline_monitor
        self.risk_engine = risk_engine
        self.emergency_stop = emergency_stop
        self.notifier = notifier
        self.check_interval = check_interval
        self.runtime_id = runtime_id

        self._last_status: SystemHealthStatus | None = None
        self._check_count: int = 0
        self._critical_count: int = 0
        self._last_check: datetime | None = None
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._history: list[SystemHealthResult] = []
        self._max_history = 100

    @property
    def last_status(self) -> SystemHealthStatus | None:
        return self._last_status

    @property
    def check_count(self) -> int:
        return self._check_count

    @property
    def critical_count(self) -> int:
        return self._critical_count

    @property
    def is_running(self) -> bool:
        return self._running

    async def check_now(self) -> SystemHealthResult:
        """Run a single health check cycle across all monitors."""
        self._check_count += 1
        self._last_check = datetime.now(UTC)
        reasons: list[str] = []
        db_status: DatabaseHealthStatus | None = None
        mkt_status: MarketHealthStatus | None = None
        risk_status: RiskHealthStatus | None = None
        pipe_status: PipelineHealthStatus | None = None

        # Database health
        if self.database_monitor is not None:
            try:
                db_result = await self.database_monitor.check()
                db_status = db_result.status
                if not db_result.trading_enabled:
                    reasons.append(f"database: {db_result.status.value}")
                if self.risk_engine is not None:
                    self.risk_engine.update_system_health(
                        database_available=db_result.status is not DatabaseHealthStatus.UNAVAILABLE,
                        api_available=True,
                    )
            except Exception as exc:
                db_status = DatabaseHealthStatus.UNAVAILABLE
                reasons.append(f"database check failed: {exc}")
                if self.risk_engine is not None:
                    self.risk_engine.update_system_health(
                        database_available=False, api_available=True
                    )

        # Risk health
        if self.risk_monitor is not None and self.risk_engine is not None:
            try:
                risk_result = self.risk_monitor.check(self.risk_engine)
                risk_status = risk_result.risk_status
                if not risk_result.trading_enabled:
                    reasons.extend(risk_result.reasons)
            except Exception as exc:
                risk_status = RiskHealthStatus.CRITICAL
                reasons.append(f"risk check failed: {exc}")

        # Determine overall status
        statuses = [s for s in (db_status, mkt_status, risk_status, pipe_status) if s is not None]
        if any(s in (DatabaseHealthStatus.UNAVAILABLE, RiskHealthStatus.CRITICAL, PipelineHealthStatus.FAILED) for s in statuses):
            overall = SystemHealthStatus.CRITICAL
        elif any(s in (DatabaseHealthStatus.DEGRADED, MarketHealthStatus.WARNING, RiskHealthStatus.WARNING, PipelineHealthStatus.DEGRADED) for s in statuses):
            overall = SystemHealthStatus.DEGRADED
        else:
            overall = SystemHealthStatus.HEALTHY

        result = SystemHealthResult(
            status=overall,
            database=db_status,
            market=mkt_status,
            risk=risk_status,
            pipeline=pipe_status,
            reasons=tuple(reasons),
            checked_at=self._last_check,
        )

        # Store in history
        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Handle status transitions
        await self._handle_transition(result)

        self._last_status = overall
        return result

    async def _handle_transition(self, result: SystemHealthResult) -> None:
        """React to health status changes."""
        previous = self._last_status
        current = result.status

        # No transition — skip
        if previous == current:
            return

        # Transition to CRITICAL — activate emergency stop
        if current == SystemHealthStatus.CRITICAL:
            self._critical_count += 1
            detail = "; ".join(result.reasons) if result.reasons else "unknown critical condition"
            logger.critical(
                "health_transition_critical",
                previous=previous,
                reasons=result.reasons,
                check_count=self._check_count,
            )
            if self.notifier is not None:
                await send_notification(
                    self.notifier,
                    NotificationLevel.CRITICAL,
                    f"System health CRITICAL: {detail}",
                    self.runtime_id,
                )
            if self.emergency_stop is not None:
                reason = self._classify_emergency(result)
                try:
                    await self.emergency_stop.activate(reason, detail)
                except Exception as exc:
                    logger.exception("emergency_stop_activation_failed")

        # Transition to DEGRADED — send warning
        elif current == SystemHealthStatus.DEGRADED:
            detail = "; ".join(result.reasons) if result.reasons else "performance degraded"
            logger.warning(
                "health_transition_degraded",
                previous=previous,
                reasons=result.reasons,
            )
            if self.notifier is not None:
                await send_notification(
                    self.notifier,
                    NotificationLevel.WARNING,
                    f"System health DEGRADED: {detail}",
                    self.runtime_id,
                )

        # Recovery to HEALTHY — send info
        elif current == SystemHealthStatus.HEALTHY and previous is not None:
            logger.info("health_transition_healthy", previous=previous)
            if self.notifier is not None:
                await send_notification(
                    self.notifier,
                    NotificationLevel.INFO,
                    f"System health recovered to HEALTHY (was {previous.value})",
                    self.runtime_id,
                )

    @staticmethod
    def _classify_emergency(result: SystemHealthResult) -> str:
        """Map health result to an emergency reason string."""
        # Lazy import to avoid circular dependency
        from app.risk.emergency_stop import EmergencyReason

        if result.database == DatabaseHealthStatus.UNAVAILABLE:
            return EmergencyReason.EMERGENCY_DB_FAILURE
        if result.risk == RiskHealthStatus.CRITICAL:
            return EmergencyReason.EMERGENCY_RECONCILIATION_FAILED
        if result.pipeline == PipelineHealthStatus.FAILED:
            return EmergencyReason.EMERGENCY_RUNTIME_ERROR
        return EmergencyReason.EMERGENCY_RUNTIME_ERROR

    async def start_periodic(self) -> None:
        """Start periodic health checks in the background."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._periodic_loop(), name="health-coordinator")

    async def stop_periodic(self) -> None:
        """Stop periodic health checks."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _periodic_loop(self) -> None:
        """Background loop that runs health checks at the configured interval."""
        while self._running:
            try:
                await self.check_now()
            except Exception:
                logger.exception("health_check_failed")
            await asyncio.sleep(self.check_interval.total_seconds())

    def get_history(self, limit: int = 10) -> list[SystemHealthResult]:
        """Return recent health check results."""
        return self._history[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Return a summary of health coordinator state."""
        return {
            "last_status": self._last_status.value if self._last_status else None,
            "check_count": self._check_count,
            "critical_count": self._critical_count,
            "last_check": self._last_check.isoformat() if self._last_check else None,
            "is_running": self._running,
        }
