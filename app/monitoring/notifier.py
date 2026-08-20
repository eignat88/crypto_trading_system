"""Notification boundaries for operational runtime events."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

import structlog


class NotificationLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Notification:
    level: NotificationLevel
    message: str
    timestamp: datetime
    runtime_id: str | None = None


class Notifier(Protocol):
    def notify(self, notification: Notification) -> object: ...


class ConsoleNotifier:
    """Structured-log notifier suitable for the initial paper soak."""

    def notify(self, notification: Notification) -> None:
        structlog.get_logger().msg(
            "runtime_notification",
            level=notification.level.value,
            message=notification.message,
            runtime_id=notification.runtime_id,
            timestamp=notification.timestamp.isoformat(),
        )


async def send_notification(
    notifier: Notifier,
    level: NotificationLevel,
    message: str,
    runtime_id: str | None = None,
) -> None:
    result = notifier.notify(Notification(level, message, datetime.now(UTC), runtime_id))
    if inspect.isawaitable(result):
        await result
