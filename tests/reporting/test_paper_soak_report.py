import json
from datetime import UTC, datetime, timedelta

from app.monitoring.heartbeat import RuntimeHealth
from app.monitoring.soak_metrics import SoakMetrics
from app.monitoring.soak_session import SoakSession, SoakStatus
from app.reporting.paper_soak_report import PaperSoakReport


def test_report_contains_validation_sections_and_writes_json(tmp_path):
    now = datetime(2026, 8, 20, tzinfo=UTC)
    session = SoakSession("runtime-1", ("BTCUSDT", "ETHUSDT"), started_at=now)
    session.finish(SoakStatus.COMPLETED, at=now + timedelta(hours=1))
    metrics = SoakMetrics()
    metrics.record_heartbeat(
        RuntimeHealth("runtime-1", "RUNNING", 3, now + timedelta(minutes=2), now, now)
    )
    metrics.increment("orders_created", 2)
    metrics.record_runtime_progress(1)

    destination = PaperSoakReport(session, metrics).write(tmp_path / "report.json")
    report = json.loads(destination.read_text(encoding="utf-8"))

    assert report["title"] == "Paper Soak Validation Report"
    assert report["runtime"]["total_uptime_seconds"] == 120
    assert report["execution"]["orders_created"] == 2
    assert report["market_data"]["events_processed"] == 1
    assert report["pipeline"]["events_processed"] == 1
