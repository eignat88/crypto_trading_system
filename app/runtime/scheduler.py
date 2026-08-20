from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TradingSchedule:
    """Calendar used to fail closed outside the scheduled paper session."""

    timezone: str = "UTC"
    start: time = time(9, 0)
    end: time = time(19, 0)
    weekdays: frozenset[int] = frozenset(range(5))

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        if self.start >= self.end:
            raise ValueError("Trading schedule end must be later than start")

    def localize(self, moment: datetime) -> datetime:
        if moment.tzinfo is None:
            raise ValueError("Trading-window checks require a timezone-aware datetime")
        return moment.astimezone(ZoneInfo(self.timezone))

    def contains(self, moment: datetime) -> bool:
        local = self.localize(moment)
        # The close boundary is exclusive: at 19:00 new orders must already be disabled.
        return local.weekday() in self.weekdays and self.start <= local.time() < self.end

    def session_id(self, moment: datetime) -> str | None:
        local = self.localize(moment)
        if not self.contains(local):
            return None
        return f"paper_session_{local:%Y%m%d}"

    def close_at(self, moment: datetime) -> datetime | None:
        local = self.localize(moment)
        if not self.contains(local):
            return None
        return datetime.combine(local.date(), self.end, tzinfo=local.tzinfo)

    def seconds_until_close(self, moment: datetime) -> float | None:
        close = self.close_at(moment)
        return None if close is None else max(0.0, (close - self.localize(moment)).total_seconds())


DEFAULT_TRADING_SCHEDULE = TradingSchedule()


def is_trading_window(
    moment: datetime | None = None,
    *,
    schedule: TradingSchedule = DEFAULT_TRADING_SCHEDULE,
) -> bool:
    """Return whether new entries are allowed (Monday-Friday, 09:00-19:00)."""

    current = moment or datetime.now(ZoneInfo(schedule.timezone))
    return schedule.contains(current)


def parse_hhmm(value: str) -> time:
    """Parse a strict 24-hour HH:MM setting."""

    if re.fullmatch(r"\d{2}:\d{2}", value) is None:
        raise ValueError(f"Invalid time {value!r}; expected HH:MM")
    try:
        parsed = datetime.strptime(value, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"Invalid time {value!r}; expected HH:MM") from exc
    return parsed.time()
