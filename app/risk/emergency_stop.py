"""Idempotent, fail-closed emergency shutdown coordinator."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from enum import StrEnum

import structlog

from app.monitoring.notifier import NotificationLevel, Notifier, send_notification


class EmergencyReason(StrEnum):
    EMERGENCY_DB_FAILURE = "EMERGENCY_DB_FAILURE"
    EMERGENCY_MARKET_DATA_STALE = "EMERGENCY_MARKET_DATA_STALE"
    EMERGENCY_RECONCILIATION_FAILED = "EMERGENCY_RECONCILIATION_FAILED"
    EMERGENCY_RUNTIME_ERROR = "EMERGENCY_RUNTIME_ERROR"
    EMERGENCY_MANUAL_STOP = "EMERGENCY_MANUAL_STOP"


class EmergencyStop:
    def __init__(
        self,
        *,
        disable_trading: Callable[[], object],
        close_execution: Callable[[], object],
        save_checkpoint: Callable[[], object],
        record_risk_event: Callable[[EmergencyReason, str], object],
        stop_runtime: Callable[[], object],
        notifier: Notifier,
        runtime_id: str | None = None,
    ) -> None:
        self.disable_trading = disable_trading
        self.close_execution = close_execution
        self.save_checkpoint = save_checkpoint
        self.record_risk_event = record_risk_event
        self.stop_runtime = stop_runtime
        self.notifier = notifier
        self.runtime_id = runtime_id
        self.active = False
        self.reason: EmergencyReason | None = None
        self._lock = asyncio.Lock()

    @staticmethod
    async def _call(callback: Callable[..., object], *args: object) -> None:
        result = callback(*args)
        if inspect.isawaitable(result):
            await result

    async def activate(self, reason: EmergencyReason, detail: str = "") -> bool:
        """Activate once; attempt every safety step even if an earlier step fails."""
        async with self._lock:
            if self.active:
                return False
            self.active = True
            self.reason = reason
            errors: list[Exception] = []
            for callback, args in (
                (self.disable_trading, ()),
                (self.close_execution, ()),
                (self.save_checkpoint, ()),
                (self.record_risk_event, (reason, detail)),
            ):
                try:
                    await self._call(callback, *args)
                except Exception as exc:  # keep progressing toward a safe stop
                    errors.append(exc)
                    structlog.get_logger().exception("emergency_stop_step_failed")
            await send_notification(
                self.notifier,
                NotificationLevel.CRITICAL,
                f"Emergency stop activated: {reason.value}" + (f" ({detail})" if detail else ""),
                self.runtime_id,
            )
            try:
                await self._call(self.stop_runtime)
            except Exception as exc:
                errors.append(exc)
            if errors:
                raise ExceptionGroup("emergency stop completed with errors", errors)
            return True
