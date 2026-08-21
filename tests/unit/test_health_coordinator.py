"""Tests for HealthCoordinator — wires monitors to emergency stop and alerts."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.monitoring.database_health import DatabaseHealthMonitor, DatabaseHealthResult, DatabaseHealthStatus
from app.monitoring.health_coordinator import HealthCoordinator, SystemHealthResult, SystemHealthStatus
from app.monitoring.market_health import MarketHealthMonitor, MarketHealthResult, MarketHealthStatus
from app.monitoring.notifier import Notification, NotificationLevel, Notifier
from app.monitoring.pipeline_health import PipelineHealthMonitor, PipelineHealthResult, PipelineHealthStatus
from app.monitoring.risk_health import RiskHealthMonitor, RiskHealthResult, RiskHealthStatus
from app.risk.emergency_stop import EmergencyReason, EmergencyStop
from app.risk.risk_engine import RiskConfig, RiskEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeNotifier:
    """Collects notifications for assertions."""

    def __init__(self) -> None:
        self.notifications: list[Notification] = []

    def notify(self, notification: Notification) -> None:
        self.notifications.append(notification)


class FakeDatabaseMonitor:
    """Configurable database health monitor for tests."""

    def __init__(self, result: DatabaseHealthResult | None = None) -> None:
        self._result = result or DatabaseHealthResult(
            "postgres", DatabaseHealthStatus.OK, 10.0, True, True
        )

    async def check(self) -> DatabaseHealthResult:
        return self._result


class FakeRiskEngine:
    """Minimal risk engine stub for coordinator tests."""

    def __init__(self) -> None:
        self.config = RiskConfig()
        self.database_available = True
        self.api_available = True
        self.reconciliation_ok = True
        self.is_emergency_stop = False
        self.peak_equity = Decimal("1000")
        self.current_equity = Decimal("950")
        self.daily_pnl = Decimal("-50")
        self.weekly_pnl = Decimal("-100")

    def update_system_health(self, *, database_available: bool, api_available: bool) -> None:
        self.database_available = database_available
        self.api_available = api_available


class FakeEmergencyStop:
    """Records emergency stop activations."""

    def __init__(self) -> None:
        self.activations: list[tuple[EmergencyReason, str]] = []
        self.active = False

    async def activate(self, reason: EmergencyReason, detail: str = "") -> bool:
        self.activations.append((reason, detail))
        self.active = True
        return True


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHealthCoordinatorInit:
    def test_creates_with_defaults(self) -> None:
        coordinator = HealthCoordinator()
        assert coordinator.last_status is None
        assert coordinator.check_count == 0
        assert coordinator.is_running is False

    def test_creates_with_all_monitors(self) -> None:
        db_monitor = FakeDatabaseMonitor()
        risk_engine = FakeRiskEngine()
        notifier = FakeNotifier()
        emergency = FakeEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            risk_engine=risk_engine,
            notifier=notifier,
            emergency_stop=emergency,
            runtime_id="test-runtime",
        )
        assert coordinator.database_monitor is db_monitor
        assert coordinator.risk_engine is risk_engine
        assert coordinator.notifier is notifier
        assert coordinator.emergency_stop is emergency
        assert coordinator.runtime_id == "test-runtime"


class TestCheckNow:
    @pytest.mark.asyncio
    async def test_healthy_status(self) -> None:
        db_monitor = FakeDatabaseMonitor()
        risk_engine = FakeRiskEngine()
        notifier = FakeNotifier()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            risk_engine=risk_engine,
            notifier=notifier,
        )
        result = await coordinator.check_now()

        assert result.status == SystemHealthStatus.HEALTHY
        assert result.database == DatabaseHealthStatus.OK
        assert coordinator.last_status == SystemHealthStatus.HEALTHY
        assert coordinator.check_count == 1
        # No notifications for healthy status
        assert len(notifier.notifications) == 0

    @pytest.mark.asyncio
    async def test_critical_db_failure_triggers_emergency(self) -> None:
        db_monitor = FakeDatabaseMonitor(
            DatabaseHealthResult("postgres", DatabaseHealthStatus.UNAVAILABLE, 100.0, False, False)
        )
        risk_engine = FakeRiskEngine()
        notifier = FakeNotifier()
        emergency = FakeEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            risk_engine=risk_engine,
            notifier=notifier,
            emergency_stop=emergency,
            runtime_id="test-runtime",
        )
        result = await coordinator.check_now()

        assert result.status == SystemHealthStatus.CRITICAL
        assert result.database == DatabaseHealthStatus.UNAVAILABLE
        assert coordinator.critical_count == 1
        # Emergency stop activated
        assert len(emergency.activations) == 1
        assert emergency.activations[0][0] == EmergencyReason.EMERGENCY_DB_FAILURE
        # Critical notification sent
        critical_notifs = [n for n in notifier.notifications if n.level == NotificationLevel.CRITICAL]
        assert len(critical_notifs) == 1
        assert "CRITICAL" in critical_notifs[0].message

    @pytest.mark.asyncio
    async def test_critical_risk_triggers_emergency(self) -> None:
        risk_monitor = MagicMock()
        risk_monitor.check = MagicMock(
            return_value=RiskHealthResult(
                RiskHealthStatus.CRITICAL, Decimal("0.8"), Decimal("0.15"), False,
                ("maximum drawdown exceeded",)
            )
        )
        risk_engine = FakeRiskEngine()
        notifier = FakeNotifier()
        emergency = FakeEmergencyStop()

        coordinator = HealthCoordinator(
            risk_monitor=risk_monitor,
            risk_engine=risk_engine,
            notifier=notifier,
            emergency_stop=emergency,
        )
        result = await coordinator.check_now()

        assert result.status == SystemHealthStatus.CRITICAL
        assert "maximum drawdown exceeded" in result.reasons
        assert len(emergency.activations) == 1

    @pytest.mark.asyncio
    async def test_degraded_sends_warning(self) -> None:
        db_monitor = FakeDatabaseMonitor(
            DatabaseHealthResult("postgres", DatabaseHealthStatus.DEGRADED, 600.0, True, False)
        )
        notifier = FakeNotifier()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            notifier=notifier,
        )
        result = await coordinator.check_now()

        assert result.status == SystemHealthStatus.DEGRADED
        warning_notifs = [n for n in notifier.notifications if n.level == NotificationLevel.WARNING]
        assert len(warning_notifs) == 1

    @pytest.mark.asyncio
    async def test_recovery_sends_info(self) -> None:
        db_monitor = FakeDatabaseMonitor(
            DatabaseHealthResult("postgres", DatabaseHealthStatus.UNAVAILABLE, 100.0, False, False)
        )
        notifier = FakeNotifier()
        emergency = FakeEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            notifier=notifier,
            emergency_stop=emergency,
        )

        # First check: critical
        await coordinator.check_now()
        assert coordinator.last_status == SystemHealthStatus.CRITICAL

        # Recover database
        db_monitor._result = DatabaseHealthResult(
            "postgres", DatabaseHealthStatus.OK, 10.0, True, True
        )

        # Second check: healthy (recovery)
        await coordinator.check_now()
        assert coordinator.last_status == SystemHealthStatus.HEALTHY

        info_notifs = [n for n in notifier.notifications if n.level == NotificationLevel.INFO]
        assert len(info_notifs) == 1
        assert "recovered" in info_notifs[0].message.lower()

    @pytest.mark.asyncio
    async def test_risk_engine_health_fed(self) -> None:
        db_monitor = FakeDatabaseMonitor(
            DatabaseHealthResult("postgres", DatabaseHealthStatus.UNAVAILABLE, 100.0, False, False)
        )
        risk_engine = FakeRiskEngine()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            risk_engine=risk_engine,
        )
        await coordinator.check_now()

        assert risk_engine.database_available is False

    @pytest.mark.asyncio
    async def test_history_tracking(self) -> None:
        coordinator = HealthCoordinator()
        await coordinator.check_now()
        await coordinator.check_now()

        assert len(coordinator.get_history()) == 2
        assert coordinator.check_count == 2

    @pytest.mark.asyncio
    async def test_summary(self) -> None:
        coordinator = HealthCoordinator()
        await coordinator.check_now()

        summary = coordinator.get_summary()
        assert summary["check_count"] == 1
        assert summary["last_status"] == "HEALTHY"
        assert summary["is_running"] is False


class TestPeriodicLoop:
    @pytest.mark.asyncio
    async def test_start_and_stop(self) -> None:
        coordinator = HealthCoordinator(check_interval=timedelta(milliseconds=10))
        await coordinator.start_periodic()
        assert coordinator.is_running is True

        await asyncio.sleep(50)  # let a few checks run
        await coordinator.stop_periodic()
        assert coordinator.is_running is False
        assert coordinator.check_count > 0

    @pytest.mark.asyncio
    async def test_no_double_start(self) -> None:
        coordinator = HealthCoordinator(check_interval=timedelta(hours=1))
        await coordinator.start_periodic()
        await coordinator.start_periodic()  # should be no-op
        assert coordinator.is_running is True
        await coordinator.stop_periodic()


class TestClassifyEmergency:
    def test_db_failure(self) -> None:
        result = SystemHealthResult(
            SystemHealthStatus.CRITICAL,
            database=DatabaseHealthStatus.UNAVAILABLE,
        )
        assert HealthCoordinator._classify_emergency(result) == EmergencyReason.EMERGENCY_DB_FAILURE

    def test_risk_critical(self) -> None:
        result = SystemHealthResult(
            SystemHealthStatus.CRITICAL,
            risk=RiskHealthStatus.CRITICAL,
        )
        assert HealthCoordinator._classify_emergency(result) == EmergencyReason.EMERGENCY_RECONCILIATION_FAILED

    def test_pipeline_failed(self) -> None:
        result = SystemHealthResult(
            SystemHealthStatus.CRITICAL,
            pipeline=PipelineHealthStatus.FAILED,
        )
        assert HealthCoordinator._classify_emergency(result) == EmergencyReason.EMERGENCY_RUNTIME_ERROR

    def test_unknown_defaults_to_runtime_error(self) -> None:
        result = SystemHealthResult(SystemHealthStatus.CRITICAL)
        assert HealthCoordinator._classify_emergency(result) == EmergencyReason.EMERGENCY_RUNTIME_ERROR
