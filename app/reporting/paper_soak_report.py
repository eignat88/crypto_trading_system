"""Generate durable JSON and human-readable paper soak validation reports."""

from __future__ import annotations

import json
from pathlib import Path

from app.monitoring.soak_metrics import SoakMetrics
from app.monitoring.soak_session import SoakSession


class PaperSoakReport:
    def __init__(self, session: SoakSession, metrics: SoakMetrics) -> None:
        self.session = session
        self.metrics = metrics

    def to_dict(self) -> dict[str, object]:
        metric_data = self.metrics.to_dict()
        lags = [float(item["lag_seconds"]) for item in metric_data["market_data_lag"]]
        heartbeats = metric_data["heartbeats"]
        counters = metric_data["counters"]
        return {
            "title": "Paper Soak Validation Report",
            "session": self.session.to_dict(),
            "runtime": {
                "total_uptime_seconds": max(
                    (float(item["uptime_seconds"]) for item in heartbeats), default=0.0
                ),
                "restarts": counters.get("restarts", 0),
                "failures": counters.get("failures", 0),
                "emergency_stops": counters.get("emergency_stops", 0),
            },
            "market_data": {
                "events_processed": counters.get("market_events", 0),
                "average_lag_seconds": sum(lags) / len(lags) if lags else 0.0,
                "max_lag_seconds": max(lags, default=0.0),
                "missing_intervals": sum(
                    int(item["missed_intervals"])
                    for item in metric_data["market_data_lag"]
                ),
            },
            "pipeline": {
                "events_processed": counters.get("pipeline_events", 0),
                "indicator_readiness": counters.get("indicator_ready", 0),
                "strategy_executions": counters.get("strategy_executions", 0),
            },
            "risk": {
                "max_drawdown": max(
                    (float(item["drawdown"]) for item in metric_data["risk_snapshots"]),
                    default=0.0,
                ),
                "risk_violations": len(metric_data["violations"]),
            },
            "execution": {
                key: counters.get(key, 0)
                for key in ("orders_created", "orders_filled", "duplicate_orders", "failed_orders")
            },
            "evidence": metric_data,
        }

    def write(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")
        return destination


def generate_paper_soak_report(
    session: SoakSession, metrics: SoakMetrics, output_report: str | Path
) -> Path:
    return PaperSoakReport(session, metrics).write(output_report)
