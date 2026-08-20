from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.monitoring.heartbeat import RuntimeHealth
from app.monitoring.risk_health import RiskHealthResult, RiskHealthStatus
from app.monitoring.soak_metrics import SoakMetrics
from scripts.run_paper_soak import record_risk_status


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


def test_runtime_progress_counts_deltas_only() -> None:
    metrics = SoakMetrics()

    assert [metrics.record_runtime_progress(value) for value in (5, 5, 7)] == [5, 0, 2]
    assert metrics.counters["market_events"] == 7
    assert metrics.counters["pipeline_events"] == 7


def test_runtime_progress_with_no_events_keeps_report_counters_empty() -> None:
    metrics = SoakMetrics()

    assert metrics.record_runtime_progress(0) == 0
    assert metrics.counters.get("market_events", 0) == 0
    assert metrics.counters.get("pipeline_events", 0) == 0


def test_risk_block_is_recorded_as_warning_without_raising(capsys):
    metrics = SoakMetrics()
    risk = RiskHealthResult(
        RiskHealthStatus.CRITICAL,
        Decimal("0"),
        Decimal("0"),
        False,
        ("warmup_not_ready",),
    )

    record_risk_status(risk, metrics)

    assert metrics.violations == ["warmup_not_ready"]
    assert capsys.readouterr().out == (
        "risk_status=BLOCKED\nrisk_warning=warmup_not_ready\n"
    )
