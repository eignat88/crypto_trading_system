from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.runtime.scheduler import TradingSchedule


@dataclass(frozen=True)
class TradingSession:
    session_id: str
    started_at: datetime
    scheduled_close_at: datetime


class SessionManager:
    """Creates one deterministic session identity for a scheduled application run."""

    def __init__(
        self,
        schedule: TradingSchedule,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.schedule = schedule
        self._clock = clock or (lambda: datetime.now(UTC))
        self.current: TradingSession | None = None

    def open(self) -> TradingSession | None:
        now = self._clock()
        session_id = self.schedule.session_id(now)
        close_at = self.schedule.close_at(now)
        if session_id is None or close_at is None:
            self.current = None
            return None
        self.current = TradingSession(session_id, now, close_at)
        return self.current

    def entries_allowed(self) -> bool:
        return self.current is not None and self.schedule.contains(self._clock())

    def seconds_until_close(self) -> float | None:
        if self.current is None:
            return None
        return self.schedule.seconds_until_close(self._clock())

    def close(self) -> TradingSession | None:
        previous = self.current
        self.current = None
        return previous
