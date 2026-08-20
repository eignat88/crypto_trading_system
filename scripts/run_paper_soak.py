#!/usr/bin/env python3
"""Run a bounded, evidence-producing paper trading soak session."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings, TradingMode  # noqa: E402
from app.monitoring.pipeline_health import PipelineHealthMonitor  # noqa: E402
from app.monitoring.risk_health import RiskHealthMonitor, RiskHealthResult  # noqa: E402
from app.monitoring.soak_metrics import SoakMetrics  # noqa: E402
from app.monitoring.soak_session import SoakSession, SoakStatus  # noqa: E402
from app.reporting.paper_soak_report import generate_paper_soak_report  # noqa: E402
from app.runtime.dependencies import build_paper_dependencies  # noqa: E402
from app.runtime.paper_application import PaperApplication  # noqa: E402

ALLOWED_SYMBOLS = frozenset({"BTCUSDT", "ETHUSDT"})


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-hours", type=float, default=1.0)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--start-time", type=_timestamp)
    parser.add_argument("--end-time", type=_timestamp)
    parser.add_argument("--output-report", default="artifacts/paper_soak_report.json")
    parser.add_argument("--sample-seconds", type=float, default=60.0, help=argparse.SUPPRESS)
    return parser


def validate_args(
    args: argparse.Namespace, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    symbols = [symbol.upper() for symbol in args.symbols]
    invalid = sorted(set(symbols) - ALLOWED_SYMBOLS)
    if invalid:
        raise ValueError(f"paper soak only permits BTCUSDT and ETHUSDT: {', '.join(invalid)}")
    if args.duration_hours <= 0:
        raise ValueError("duration-hours must be positive")
    if args.sample_seconds <= 0:
        raise ValueError("sample-seconds must be positive")
    start = args.start_time or now or datetime.now(UTC)
    end = args.end_time or start + timedelta(hours=args.duration_hours)
    if end <= start:
        raise ValueError("end-time must be after start-time")
    args.symbols = symbols
    return start, end


def record_risk_status(risk: RiskHealthResult, metrics: SoakMetrics) -> None:
    """Record a risk trading block without treating the healthy runtime as failed.

    A risk block is an expected fail-closed operating state (for example while
    market warmup is incomplete).  The evidence remains visible in the report,
    but only an actual runtime/pipeline failure terminates the soak.
    """
    status = risk.risk_status.value if risk.trading_enabled else "BLOCKED"
    print(f"risk_status={status}", flush=True)
    if not risk.trading_enabled:
        metrics.violations.extend(risk.reasons)
        print(f"risk_warning={','.join(risk.reasons)}", flush=True)


async def run_soak(args: argparse.Namespace) -> SoakSession:
    start, end = validate_args(args)
    mode = os.getenv("TRADING_MODE", "paper").lower()
    if mode != "paper":
        raise RuntimeError(f"Soak runner refuses TRADING_MODE={mode}")
    delay = (start - datetime.now(UTC)).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)

    settings = Settings(trading_mode=TradingMode.PAPER, trading_symbols=",".join(args.symbols))
    dependencies = await build_paper_dependencies(settings)
    runtime_id = dependencies.heartbeat.runtime_id if dependencies.heartbeat else "paper-runtime"
    session = SoakSession(runtime_id=runtime_id, symbols=tuple(args.symbols), started_at=start)
    metrics = SoakMetrics()
    application = PaperApplication(dependencies)
    stop_requested = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_requested.set)
            installed.append(signum)
        except NotImplementedError:  # pragma: no cover
            pass

    print("SOAK_STARTED", flush=True)
    try:
        await application.start()
        for state in application.lifecycle.history:
            metrics.record_lifecycle(state.name, datetime.now(UTC))
        pipeline_monitor = PipelineHealthMonitor()
        risk_monitor = RiskHealthMonitor()
        while datetime.now(UTC) < end:
            if stop_requested.is_set():
                session.finish(SoakStatus.ABORTED, "termination signal received")
                break
            run_task = application._run_task
            if run_task is not None and run_task.done():
                error = run_task.exception()
                detail = error or "event stream ended"
                raise RuntimeError(f"paper runtime stopped unexpectedly: {detail}")
            if dependencies.heartbeat is not None:
                heartbeat = await dependencies.heartbeat.beat(
                    state="RUNNING", sequence=dependencies.runtime.last_checkpoint_sequence
                )
                metrics.record_heartbeat(heartbeat)
                print("heartbeat_ok", flush=True)
            pipeline = pipeline_monitor.check()
            metrics.record_pipeline(pipeline)
            pipeline_label = "HEALTHY" if pipeline.trading_enabled else pipeline.status.value
            print(f"pipeline_health={pipeline_label}", flush=True)
            risk = risk_monitor.check(dependencies.risk_engine)
            record_risk_status(risk, metrics)
            remaining = max(0.0, (end - datetime.now(UTC)).total_seconds())
            await asyncio.sleep(min(args.sample_seconds, remaining))
        if session.status is SoakStatus.RUNNING:
            session.finish(SoakStatus.COMPLETED)
    except asyncio.CancelledError:
        session.finish(SoakStatus.ABORTED, "runner cancelled")
        raise
    except Exception as exc:
        if session.status is SoakStatus.RUNNING:
            session.finish(SoakStatus.FAILED, str(exc))
        metrics.increment("failures")
    finally:
        try:
            await application.stop()
            print("checkpoint_ok", flush=True)
        except Exception as exc:
            if session.status is SoakStatus.RUNNING:
                session.finish(SoakStatus.FAILED, f"shutdown failed: {exc}")
            elif session.status is SoakStatus.COMPLETED:
                session.status = SoakStatus.FAILED
                session.failure_reason = f"shutdown failed: {exc}"
        for state in application.lifecycle.history[len(metrics.lifecycle) :]:
            metrics.record_lifecycle(state.name, datetime.now(UTC))
        generate_paper_soak_report(session, metrics, args.output_report)
        for signum in installed:
            loop.remove_signal_handler(signum)
    print(f"SOAK_{session.status.value}", flush=True)
    return session


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        session = await run_soak(args)
    except (ValueError, RuntimeError, OSError) as exc:
        structlog.get_logger().critical("paper_soak_startup_failed", error=str(exc))
        return 1
    return 0 if session.status is SoakStatus.COMPLETED else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
