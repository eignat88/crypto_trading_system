from datetime import UTC, datetime, timedelta

import pytest

from app.monitoring.soak_session import SoakSession, SoakStatus


def test_soak_session_tracks_terminal_state_and_duration():
    started = datetime(2026, 8, 20, tzinfo=UTC)
    session = SoakSession("runtime-1", ("btcusdt", "ETHUSDT"), started_at=started)
    session.finish(SoakStatus.COMPLETED, at=started + timedelta(hours=1))

    assert session.symbols == ("BTCUSDT", "ETHUSDT")
    assert session.duration == 3600
    assert session.to_dict()["status"] == "COMPLETED"


def test_failed_session_requires_evidence():
    session = SoakSession("runtime-1", ("BTCUSDT",))
    with pytest.raises(ValueError, match="failure reason"):
        session.finish(SoakStatus.FAILED)
