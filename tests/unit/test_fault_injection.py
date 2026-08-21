"""Fault-injection tests: verify every critical failure blocks new entries,
preserves diagnostic trail, and allows safe recovery.

Criteria from DEVELOPMENT_PLAN_2026-08-19.md §P1:
  "fault-injection тесты подтверждают, что каждый критический сбой блокирует
   новые входы, сохраняет диагностический след и допускает безопасное
   восстановление."
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.monitoring.database_health import DatabaseHealthMonitor, DatabaseHealthResult, DatabaseHealthStatus
from app.monitoring.health_coordinator import HealthCoordinator, SystemHealthStatus
from app.monitoring.notifier import Notification, NotificationLevel
from app.monitoring.risk_health import RiskHealthMonitor, RiskHealthResult, RiskHealthStatus
from app.reconciliation.paper_reconciler import (
    Discrepancy,
    DiscrepancySeverity,
    PaperReconciler,
    ReconciliationResult,
)
from app.risk.emergency_stop import EmergencyReason, EmergencyStop
from app.risk.risk_engine import RiskConfig, RiskEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class RecordingNotifier:
    """Collects notifications for assertions."""

    def __init__(self) -> None:
        self.notifications: list[Notification] = []

    def notify(self, notification: Notification) -> None:
        self.notifications.append(notification)


class RecordingEmergencyStop:
    """Records activations for assertions."""

    def __init__(self) -> None:
        self.activations: list[tuple[EmergencyReason, str]] = []
        self.active = False

    async def activate(self, reason: EmergencyReason, detail: str = "") -> bool:
        self.activations.append((reason, detail))
        self.active = True
        return True


class FailableDatabaseMonitor:
    """Database monitor that can be toggled to simulate failures."""

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail

    def set_fail(self, fail: bool) -> None:
        self._fail = fail

    async def check(self) -> DatabaseHealthResult:
        if self._fail:
            return DatabaseHealthResult(
                "postgres", DatabaseHealthStatus.UNAVAILABLE, 100.0, False, False, "connection refused"
            )
        return DatabaseHealthResult("postgres", DatabaseHealthStatus.OK, 10.0, True, True)


class FakeRiskEngine:
    """Risk engine stub that tracks state changes."""

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
        self._updates: list[dict[str, Any]] = []

    def update_system_health(self, *, database_available: bool, api_available: bool) -> None:
        self.database_available = database_available
        self.api_available = api_available
        self._updates.append({"database_available": database_available, "api_available": api_available})

    def update_reconciliation(self, successful: bool) -> None:
        self.reconciliation_ok = successful
        self._updates.append({"reconciliation_ok": successful})

    def check_trade(self, **kwargs: Any) -> Any:
        """Simulate risk check — block if reconciliation failed."""
        result = MagicMock()
        result.approved = self.reconciliation_ok and not self.is_emergency_stop
        result.risk_level = MagicMock()
        result.risk_level.value = "LOW"
        result.events = []
        result.reasons = []
        result.adjusted_quantity = None
        return result


class FakeStateReader:
    """In-memory state for reconciler tests."""

    def __init__(
        self,
        balance: Decimal = Decimal("100"),
        orders: dict[str, Any] | None = None,
        fills: dict[str, Any] | None = None,
        positions: dict[str, Any] | None = None,
    ) -> None:
        self._balance = balance
        self._orders = orders or {}
        self._fills = fills or {}
        self._positions = positions or {}

    @property
    def cash_balance(self) -> Decimal:
        return self._balance

    @property
    def orders(self) -> dict[str, Any]:
        return self._orders

    @property
    def fills(self) -> dict[str, Any]:
        return self._fills

    @property
    def positions(self) -> dict[str, Any]:
        return self._positions


class FakeDatabaseReader:
    """Database state for reconciler tests."""

    def __init__(
        self,
        state: Any = None,
        orders: list[dict[str, Any]] | None = None,
        fills: list[dict[str, Any]] | None = None,
        positions: list[Any] | None = None,
    ) -> None:
        from dataclasses import dataclass

        @dataclass
        class _State:
            cash_balance: Decimal = Decimal("100")
            last_market_sequence: int = 0

        self._state = state or _State()
        self._orders = orders or []
        self._fills = fills or []
        self._positions = positions or []

    async def load_state(self) -> Any:
        return self._state

    async def load_orders(self) -> list[dict[str, Any]]:
        return self._orders

    async def load_fills(self) -> list[dict[str, Any]]:
        return self._fills

    async def load_positions(self) -> list[Any]:
        return self._positions


# ---------------------------------------------------------------------------
# Fault-injection tests
# ---------------------------------------------------------------------------


class TestDatabaseFailureInjection:
    """Inject DB failure → verify emergency stop + notification + blocking."""

    @pytest.mark.asyncio
    async def test_db_outage_triggers_emergency_stop(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=True)
        notifier = RecordingNotifier()
        emergency = RecordingEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            notifier=notifier,
            emergency_stop=emergency,
            runtime_id="fault-test",
        )
        result = await coordinator.check_now()

        assert result.status == SystemHealthStatus.CRITICAL
        assert len(emergency.activations) == 1
        assert emergency.activations[0][0] == EmergencyReason.EMERGENCY_DB_FAILURE
        assert emergency.active is True

    @pytest.mark.asyncio
    async def test_db_outage_sends_critical_notification(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=True)
        notifier = RecordingNotifier()
        emergency = RecordingEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            notifier=notifier,
            emergency_stop=emergency,
        )
        await coordinator.check_now()

        critical = [n for n in notifier.notifications if n.level == NotificationLevel.CRITICAL]
        assert len(critical) == 1
        assert "CRITICAL" in critical[0].message

    @pytest.mark.asyncio
    async def test_db_outage_feeds_risk_engine(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=True)
        risk_engine = FakeRiskEngine()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            risk_engine=risk_engine,
        )
        await coordinator.check_now()

        assert risk_engine.database_available is False

    @pytest.mark.asyncio
    async def test_recovery_after_db_outage(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=True)
        notifier = RecordingNotifier()
        emergency = RecordingEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            notifier=notifier,
            emergency_stop=emergency,
        )

        # Fail
        await coordinator.check_now()
        assert coordinator.last_status == SystemHealthStatus.CRITICAL

        # Recover
        db_monitor.set_fail(False)
        await coordinator.check_now()
        assert coordinator.last_status == SystemHealthStatus.HEALTHY

        info = [n for n in notifier.notifications if n.level == NotificationLevel.INFO]
        assert len(info) == 1
        assert "recovered" in info[0].message.lower()


class TestReconciliationFailureInjection:
    """Inject reconciliation mismatch → verify risk engine blocks trading."""

    @pytest.mark.asyncio
    async def test_balance_mismatch_blocks_trading(self) -> None:
        risk_engine = FakeRiskEngine()
        state_reader = FakeStateReader(balance=Decimal("100"))
        db_reader = FakeDatabaseReader(state=type("_S", (), {"cash_balance": Decimal("50"), "last_market_sequence": 0})())

        reconciler = PaperReconciler(
            state_reader=state_reader,
            db_reader=db_reader,
        )
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        risk_engine.update_reconciliation(not result.has_fatal)
        assert risk_engine.reconciliation_ok is False

        # Verify risk engine blocks new trades
        trade_result = risk_engine.check_trade(
            symbol="BTCUSDT", side="buy", quantity=Decimal("0.01"),
            price=Decimal("100"), current_balance=Decimal("100"),
            current_positions={}, total_capital=Decimal("100"),
        )
        assert trade_result.approved is False

    @pytest.mark.asyncio
    async def test_position_drift_blocks_trading(self) -> None:
        from dataclasses import dataclass

        @dataclass
        class Pos:
            symbol: str
            quantity: Decimal
            average_price: Decimal

        risk_engine = FakeRiskEngine()
        state_reader = FakeStateReader(
            positions={"BTCUSDT": Pos("BTCUSDT", Decimal("0.01"), Decimal("100"))}
        )
        db_reader = FakeDatabaseReader(
            positions=[Pos("BTCUSDT", Decimal("0.05"), Decimal("100"))]
        )

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        assert any(d.category == "position_quantity_mismatch" for d in result.discrepancies)

    @pytest.mark.asyncio
    async def test_recoverable_discrepancy_allows_trading(self) -> None:
        from dataclasses import dataclass

        @dataclass
        class Ord:
            order_id: str
            symbol: str
            side: str
            quantity: Decimal
            status: str
            created_at: datetime

        risk_engine = FakeRiskEngine()
        now = datetime.now(UTC)
        state_reader = FakeStateReader(
            orders={"o1": Ord("o1", "BTCUSDT", "buy", Decimal("0.01"), "FILLED", now)}
        )
        db_reader = FakeDatabaseReader(orders=[])

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is False
        risk_engine.update_reconciliation(not result.has_fatal)
        assert risk_engine.reconciliation_ok is True


class TestStaleDataInjection:
    """Inject stale market data → verify risk engine blocks trading."""

    @pytest.mark.asyncio
    async def test_stale_data_blocks_trading(self) -> None:
        engine = RiskEngine(RiskConfig(stale_data_threshold_minutes=5))
        engine.update_data_time(datetime.now(UTC) - timedelta(minutes=10))

        result = engine.check_trade(
            symbol="BTCUSDT", side="buy", quantity=Decimal("0.01"),
            price=Decimal("100"), current_balance=Decimal("500"),
            current_positions={}, total_capital=Decimal("500"),
        )
        assert result.approved is False
        assert any("stale" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_fresh_data_allows_trading(self) -> None:
        engine = RiskEngine(RiskConfig(stale_data_threshold_minutes=5))
        engine.update_data_time(datetime.now(UTC))

        result = engine.check_trade(
            symbol="BTCUSDT", side="buy", quantity=Decimal("0.01"),
            price=Decimal("100"), current_balance=Decimal("500"),
            current_positions={}, total_capital=Decimal("500"),
        )
        assert result.approved is True


class TestEmergencyStopActivation:
    """Verify emergency stop blocks trading and preserves diagnostic trail."""

    @pytest.mark.asyncio
    async def test_emergency_stop_blocks_new_entries(self) -> None:
        engine = RiskEngine()
        engine.set_emergency_stop(True, "test failure")

        result = engine.check_trade(
            symbol="BTCUSDT", side="buy", quantity=Decimal("0.01"),
            price=Decimal("100"), current_balance=Decimal("500"),
            current_positions={}, total_capital=Decimal("500"),
        )
        assert result.approved is False

    @pytest.mark.asyncio
    async def test_emergency_stop_preserves_reason(self) -> None:
        engine = RiskEngine()
        engine.set_emergency_stop(True, "DB connection lost")

        assert engine.is_emergency_stop is True
        assert engine.emergency_stop_reason == "DB connection lost"

    @pytest.mark.asyncio
    async def test_risk_limit_blocks_trading(self) -> None:
        engine = RiskEngine(RiskConfig(max_drawdown=Decimal("0.10")))
        engine.peak_equity = Decimal("1000")
        engine.current_equity = Decimal("850")  # 15% drawdown

        result = engine.check_trade(
            symbol="BTCUSDT", side="buy", quantity=Decimal("0.01"),
            price=Decimal("100"), current_balance=Decimal("500"),
            current_positions={}, total_capital=Decimal("850"),
        )
        assert result.approved is False


class TestDiagnosticTrail:
    """Verify diagnostic information is preserved through failures."""

    @pytest.mark.asyncio
    async def test_coordinator_tracks_critical_count(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=True)
        emergency = RecordingEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            emergency_stop=emergency,
        )

        # First check transitions to CRITICAL
        await coordinator.check_now()
        assert coordinator.critical_count == 1
        assert len(emergency.activations) == 1

        # Subsequent checks stay CRITICAL but don't re-trigger transition
        await coordinator.check_now()
        await coordinator.check_now()
        assert coordinator.critical_count == 1  # only counts transitions
        assert coordinator.check_count == 3

    @pytest.mark.asyncio
    async def test_coordinator_reactivate_on_recovery_then_failure(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=True)
        emergency = RecordingEmergencyStop()

        coordinator = HealthCoordinator(
            database_monitor=db_monitor,
            emergency_stop=emergency,
        )

        # Fail
        await coordinator.check_now()
        assert coordinator.critical_count == 1

        # Recover
        db_monitor.set_fail(False)
        await coordinator.check_now()
        assert coordinator.last_status == SystemHealthStatus.HEALTHY

        # Fail again — counts as new transition
        db_monitor.set_fail(True)
        await coordinator.check_now()
        assert coordinator.critical_count == 2
        assert len(emergency.activations) == 2

    @pytest.mark.asyncio
    async def test_coordinator_preserves_history(self) -> None:
        db_monitor = FailableDatabaseMonitor(fail=False)
        coordinator = HealthCoordinator(database_monitor=db_monitor)

        await coordinator.check_now()
        db_monitor.set_fail(True)
        await coordinator.check_now()
        db_monitor.set_fail(False)
        await coordinator.check_now()

        history = coordinator.get_history(limit=10)
        assert len(history) == 3
        assert history[0].status == SystemHealthStatus.HEALTHY
        assert history[1].status == SystemHealthStatus.CRITICAL
        assert history[2].status == SystemHealthStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_reconciler_tracks_consecutive_fatal(self) -> None:
        state_reader = FakeStateReader(balance=Decimal("100"))
        db_reader = FakeDatabaseReader(
            state=type("_S", (), {"cash_balance": Decimal("50"), "last_market_sequence": 0})()
        )

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)

        await reconciler.reconcile()
        assert reconciler.consecutive_fatal == 1

        await reconciler.reconcile()
        assert reconciler.consecutive_fatal == 2

    @pytest.mark.asyncio
    async def test_reconciler_result_is_serializable(self) -> None:
        state_reader = FakeStateReader()
        db_reader = FakeDatabaseReader()

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        d = result.to_dict()
        assert "checked_at" in d
        assert "discrepancies" in d
        assert "orders" in d
        assert "balance" in d
