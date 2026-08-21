#!/usr/bin/env python3
"""Smoke test for crypto_trading_system paper runtime.

Runs preflight checks, executes a short soak (default 1 hour),
validates results, and generates a report.

Usage:
    python scripts/smoke_test.py                    # 1 hour soak
    python scripts/smoke_test.py --duration 2       # 2 hour soak
    python scripts/smoke_test.py --skip-preflight   # skip preflight checks
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


class SmokeTestResult:
    """Collects smoke test results."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.start_time = datetime.now(UTC)
        self.end_time: datetime | None = None
        self.passed = True

    def add_check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({
            "name": name,
            "passed": passed,
            "detail": detail,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        if not passed:
            self.passed = False
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))

    def finish(self) -> None:
        self.end_time = datetime.now(UTC)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": (
                (self.end_time - self.start_time).total_seconds()
                if self.end_time else None
            ),
            "passed": self.passed,
            "checks": self.checks,
            "summary": {
                "total": len(self.checks),
                "passed": sum(1 for c in self.checks if c["passed"]),
                "failed": sum(1 for c in self.checks if not c["passed"]),
            },
        }


def check_database(result: SmokeTestResult) -> bool:
    """Check PostgreSQL connection and schemas."""
    print("\n[1/4] Database connection...")
    try:
        import psycopg
        from app.config.settings import settings

        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()

        result.add_check("database_connection", True, f"{settings.postgres_host}:{settings.postgres_port}")
        conn.close()
        return True
    except Exception as exc:
        result.add_check("database_connection", False, str(exc))
        return False


def check_migrations(result: SmokeTestResult) -> bool:
    """Check that migrations are applied."""
    print("[2/4] Migrations...")
    try:
        import psycopg
        from app.config.settings import settings

        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM public.schema_migrations
                    WHERE version = 50
                )
            """)
            migrated = cur.fetchone()[0]

            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'paper_orders'
                )
            """)
            paper_tables = cur.fetchone()[0]

        result.add_check("migration_050", migrated, "migration 050 applied")
        result.add_check("paper_tables", paper_tables, "paper_orders exists")
        conn.close()
        return migrated and paper_tables
    except Exception as exc:
        result.add_check("migration_check", False, str(exc))
        return False


def check_bybit(result: SmokeTestResult) -> bool:
    """Check Bybit API connectivity."""
    print("[3/4] Bybit connection...")
    try:
        from app.config.settings import settings
        from app.exchange.bybit_client import BybitClient

        async def _check() -> bool:
            client = BybitClient()
            try:
                instruments = await client.get_instruments()
                return len(instruments) > 0
            finally:
                await client.close()

        ok = asyncio.run(_check())
        result.add_check("bybit_connection", ok, settings.bybit_environment)
        return ok
    except Exception as exc:
        result.add_check("bybit_connection", False, str(exc))
        return False


def run_soak(duration_hours: float, result: SmokeTestResult) -> dict[str, Any]:
    """Run short paper trading soak."""
    print(f"\n[4/4] Running smoke soak ({duration_hours}h)...")

    try:
        from app.config.settings import Settings, TradingMode
        from app.monitoring.soak_metrics import SoakMetrics
        from app.monitoring.soak_session import SoakSession, SoakStatus
        from app.reporting.paper_soak_report import generate_paper_soak_report
        from app.runtime.dependencies import build_paper_dependencies
        from app.runtime.paper_application import PaperApplication

        async def _soak() -> dict[str, Any]:
            settings = Settings(
                trading_mode=TradingMode.PAPER,
                trading_symbols="BTCUSDT,ETHUSDT",
            )
            dependencies = await build_paper_dependencies(settings)
            runtime_id = dependencies.heartbeat.runtime_id if dependencies.heartbeat else "smoke-test"
            session = SoakSession(runtime_id=runtime_id, symbols=("BTCUSDT", "ETHUSDT"))
            metrics = SoakMetrics()
            application = PaperApplication(dependencies)

            end_time = datetime.now(UTC) + timedelta(hours=duration_hours)

            try:
                await application.start()
                print(f"  Runtime started: {application.lifecycle.state.value}")

                while datetime.now(UTC) < end_time:
                    if application._run_task and application._run_task.done():
                        break
                    metrics.record_runtime_progress(dependencies.runtime.candles_processed)
                    if dependencies.heartbeat:
                        hb = await dependencies.heartbeat.beat(
                            state="RUNNING",
                            sequence=dependencies.runtime.last_processed_sequence,
                        )
                        metrics.record_heartbeat(hb)
                    await asyncio.sleep(30)

                session.finish(SoakStatus.COMPLETED)
            except Exception as exc:
                session.finish(SoakStatus.FAILED, str(exc))
            finally:
                await application.stop()
                metrics.record_runtime_progress(dependencies.runtime.candles_processed)

            report_path = Path("artifacts/smoke_soak_report.json")
            generate_paper_soak_report(session, metrics, report_path)

            return {
                "status": session.status.value,
                "failure_reason": session.failure_reason,
                "candles_processed": dependencies.runtime.candles_processed,
                "last_sequence": dependencies.runtime.last_processed_sequence,
                "report_path": str(report_path),
            }

        soak_result = asyncio.run(_soak())

        result.add_check(
            "soak_completed",
            soak_result["status"] == "COMPLETED",
            soak_result.get("failure_reason", f"candles={soak_result['candles_processed']}"),
        )
        result.add_check(
            "candles_processed",
            soak_result["candles_processed"] > 0,
            f"count={soak_result['candles_processed']}",
        )
        result.add_check(
            "sequence_positive",
            soak_result["last_sequence"] > 0,
            f"sequence={soak_result['last_sequence']}",
        )

        return soak_result
    except Exception as exc:
        result.add_check("soak_exception", False, str(exc))
        return {"status": "EXCEPTION", "error": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=1.0, help="Soak duration in hours")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight checks")
    parser.add_argument("--output", default="artifacts/smoke_test_report.json", help="Output report path")
    args = parser.parse_args()

    print("=" * 60)
    print("SMOKE TEST — Crypto Trading System")
    print(f"Duration: {args.duration} hours")
    print(f"Time: {datetime.now(UTC).isoformat()}")
    print("=" * 60)

    result = SmokeTestResult()

    # Preflight checks
    if not args.skip_preflight:
        db_ok = check_database(result)
        if not db_ok:
            print("\n❌ Database check failed. Aborting.")
            result.finish()
            _write_report(result, args.output)
            return 1

        migrations_ok = check_migrations(result)
        if not migrations_ok:
            print("\n❌ Migrations check failed. Aborting.")
            result.finish()
            _write_report(result, args.output)
            return 1

        bybit_ok = check_bybit(result)
        if not bybit_ok:
            print("\n❌ Bybit check failed. Aborting.")
            result.finish()
            _write_report(result, args.output)
            return 1
    else:
        result.add_check("preflight_skipped", True, "skipped by --skip-preflight")

    # Run soak
    soak_result = run_soak(args.duration, result)

    # Finish
    result.finish()
    _write_report(result, args.output)

    # Summary
    print("\n" + "=" * 60)
    if result.passed:
        print("✅ SMOKE TEST PASSED")
    else:
        print("❌ SMOKE TEST FAILED")
    print(f"Checks: {result.to_dict()['summary']}")
    print(f"Report: {args.output}")
    print("=" * 60)

    return 0 if result.passed else 1


def _write_report(result: SmokeTestResult, output_path: str) -> None:
    """Write smoke test report to file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
