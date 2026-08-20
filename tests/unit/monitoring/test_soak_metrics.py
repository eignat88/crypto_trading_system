from datetime import UTC, datetime, timedelta

from app.monitoring.heartbeat import RuntimeHealth
from app.monitoring.soak_metrics import SoakMetrics


def test_soak_metrics_detects_heartbeat_sequence_regression():
    now = datetime(2026, 8, 20, tzinfo=UTC)
    metrics = SoakMetrics()
    for sequence in (2, 1):
        metrics.record_heartbeat(RuntimeHealth("runtime-1", "RUNNING", sequence, now, now, now))

    assert metrics.violations == ["heartbeat sequence moved backwards"]
    assert metrics.to_dict()["heartbeats"][0]["heartbeat_time"] == now.isoformat()


def test_soak_metrics_serializes_runtime_uptime():
    now = datetime(2026, 8, 20, tzinfo=UTC)
    metrics = SoakMetrics()
    metrics.record_heartbeat(
        RuntimeHealth("runtime-1", "RUNNING", 10, now + timedelta(seconds=12), now, now)
    )
    assert metrics.to_dict()["heartbeats"][0]["uptime_seconds"] == 12
