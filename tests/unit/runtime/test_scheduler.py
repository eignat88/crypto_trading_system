from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.runtime.scheduler import TradingSchedule, is_trading_window, parse_hhmm
from app.runtime.session_manager import SessionManager


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 8, 17, 8, 59, tzinfo=UTC), False),
        (datetime(2026, 8, 17, 9, 0, tzinfo=UTC), True),
        (datetime(2026, 8, 17, 18, 59, 59, tzinfo=UTC), True),
        (datetime(2026, 8, 17, 19, 0, tzinfo=UTC), False),
        (datetime(2026, 8, 22, 12, 0, tzinfo=UTC), False),
    ],
)
def test_default_trading_window_is_weekdays_from_nine_until_nineteen(
    moment: datetime, expected: bool
) -> None:
    assert is_trading_window(moment) is expected


def test_schedule_applies_configured_timezone() -> None:
    schedule = TradingSchedule(timezone="Europe/Moscow")

    assert schedule.contains(datetime(2026, 8, 17, 6, 0, tzinfo=UTC))
    assert schedule.session_id(datetime(2026, 8, 17, 6, 0, tzinfo=UTC)) == (
        "paper_session_20260817"
    )


def test_session_manager_closes_entry_gate_when_clock_reaches_boundary() -> None:
    current = datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
    manager = SessionManager(TradingSchedule(), clock=lambda: current)

    session = manager.open()

    assert session is not None
    assert session.session_id == "paper_session_20260817"
    assert session.scheduled_close_at == datetime(2026, 8, 17, 19, 0, tzinfo=UTC)
    assert manager.entries_allowed()
    assert manager.seconds_until_close() == 10 * 60 * 60


def test_session_manager_fails_closed_outside_window() -> None:
    manager = SessionManager(
        TradingSchedule(), clock=lambda: datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
    )

    assert manager.open() is None
    assert not manager.entries_allowed()
    assert manager.seconds_until_close() is None


def test_schedule_rejects_naive_datetimes_and_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        TradingSchedule().contains(datetime(2026, 8, 17, 10, 0))
    with pytest.raises(ValueError, match="later than start"):
        TradingSchedule(start=time(19), end=time(9))
    with pytest.raises(ValueError, match="expected HH:MM"):
        parse_hhmm("9:00")


def test_dst_timezone_close_keeps_local_session_boundary() -> None:
    timezone = ZoneInfo("Europe/Berlin")
    schedule = TradingSchedule(timezone="Europe/Berlin")
    moment = datetime(2026, 8, 17, 10, 0, tzinfo=timezone)

    assert schedule.close_at(moment) == datetime(2026, 8, 17, 19, 0, tzinfo=timezone)
