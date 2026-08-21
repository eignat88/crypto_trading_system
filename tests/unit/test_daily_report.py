"""Tests for DailyReportGenerator — immutable daily paper trading reports."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.monitoring.soak_metrics import SoakMetrics
from app.reconciliation.paper_reconciler import Discrepancy, DiscrepancySeverity, ReconciliationResult
from app.reporting.daily_report import DailyReportData, DailyReportGenerator


class TestDailyReportData:
    def test_to_dict(self) -> None:
        data = DailyReportData(
            report_date=date(2026, 8, 21),
            exchange="bybit",
            symbols=("BTCUSDT",),
            run_id="run-001",
            equity=Decimal("500"),
            total_trades=5,
            winning_trades=3,
            losing_trades=2,
            reconciliation_checks=10,
            reconciliation_fatal_count=0,
        )
        d = data.to_dict()
        assert d["report_date"] == "2026-08-21"
        assert d["exchange"] == "bybit"
        assert d["pnl"]["equity"] == "500"
        assert d["trades"]["total"] == 5
        assert d["trades"]["winning"] == 3
        assert d["reconciliation"]["checks"] == 10
        assert d["reconciliation"]["fatal_count"] == 0


class TestDailyReportGenerator:
    def test_generates_with_defaults(self) -> None:
        gen = DailyReportGenerator()
        data = gen.generate()
        assert data.report_date == datetime.now(UTC).date()
        assert data.exchange == "bybit"
        assert len(data.content_hash) == 64  # SHA-256

    def test_generates_with_pnl_data(self) -> None:
        gen = DailyReportGenerator(run_id="run-123")
        pnl = {
            "equity": "550",
            "cash_balance": "200",
            "realized_pnl": "30",
            "unrealized_pnl": "20",
            "fees_paid": "1.5",
            "daily_pnl": "50",
            "previous_equity": "500",
            "total_trades": 10,
            "winning_trades": 6,
            "losing_trades": 4,
            "max_drawdown": "25",
            "max_drawdown_pct": "4.5",
            "open_positions": 1,
        }
        data = gen.generate(pnl_data=pnl, report_date=date(2026, 8, 21))

        assert data.equity == Decimal("550")
        assert data.realized_pnl == Decimal("30")
        assert data.total_trades == 10
        assert data.winning_trades == 6
        assert data.win_rate == Decimal("0.6")
        assert data.run_id == "run-123"

    def test_generates_with_reconciliation(self) -> None:
        recon = ReconciliationResult(
            checked_at=datetime.now(UTC),
            discrepancies=[
                Discrepancy("order_missing_in_db", DiscrepancySeverity.RECOVERABLE, "order pending"),
            ],
            orders_runtime=5,
            orders_db=4,
            success=True,
        )
        gen = DailyReportGenerator()
        data = gen.generate(reconciliation=recon)

        assert data.reconciliation_checks == 1
        assert data.reconciliation_recoverable_count == 1
        assert data.last_reconciliation_status == "OK"
        assert len(data.last_reconciliation_discrepancies) == 1
        assert data.last_reconciliation_discrepancies[0]["category"] == "order_missing_in_db"

    def test_generates_with_fatal_reconciliation(self) -> None:
        recon = ReconciliationResult(
            checked_at=datetime.now(UTC),
            discrepancies=[
                Discrepancy("balance_mismatch", DiscrepancySeverity.FATAL, "balance drift"),
            ],
            success=True,
        )
        gen = DailyReportGenerator()
        data = gen.generate(reconciliation=recon)

        assert data.last_reconciliation_status == "FATAL"
        assert data.reconciliation_fatal_count == 1

    def test_generates_with_soak_metrics(self) -> None:
        metrics = SoakMetrics()
        metrics.increment("market_events", 100)
        metrics.increment("errors", 2)
        metrics.increment("risk_rejections", 5)

        gen = DailyReportGenerator()
        data = gen.generate(metrics=metrics)

        assert data.candles_processed == 100
        assert data.runtime_errors == 2
        assert data.risk_rejections == 5

    def test_content_hash_is_deterministic(self) -> None:
        gen = DailyReportGenerator()
        data1 = gen.generate(report_date=date(2026, 1, 1))
        data2 = gen.generate(report_date=date(2026, 1, 1))
        assert data1.content_hash == data2.content_hash

    def test_different_dates_different_hash(self) -> None:
        gen = DailyReportGenerator()
        data1 = gen.generate(report_date=date(2026, 1, 1))
        data2 = gen.generate(report_date=date(2026, 1, 2))
        assert data1.content_hash != data2.content_hash

    def test_write_report(self, tmp_path: Path) -> None:
        gen = DailyReportGenerator(exchange="bybit", symbols=("BTCUSDT",))
        data = gen.generate(report_date=date(2026, 8, 21))

        filepath = gen.write_report(data, tmp_path)

        assert filepath.exists()
        assert filepath.name == "daily_report_2026-08-21.json"

        content = json.loads(filepath.read_text(encoding="utf-8"))
        assert content["report_date"] == "2026-08-21"
        assert content["exchange"] == "bybit"
        assert content["metadata"]["content_hash"] == data.content_hash

    def test_write_report_is_idempotent(self, tmp_path: Path) -> None:
        gen = DailyReportGenerator()
        data1 = gen.generate(report_date=date(2026, 8, 21))
        data2 = gen.generate(report_date=date(2026, 8, 21))

        gen.write_report(data1, tmp_path)
        gen.write_report(data2, tmp_path)

        content = json.loads((tmp_path / "daily_report_2026-08-21.json").read_text(encoding="utf-8"))
        assert content["metadata"]["content_hash"] == data1.content_hash
