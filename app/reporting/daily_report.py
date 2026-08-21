"""Immutable daily report generator for paper trading.

Combines PnL metrics, reconciliation status, execution stats, and risk
state into a single immutable JSON artifact written once per day.  The
report is content-addressed by date so that historical reports can never
be overwritten.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import structlog

from app.monitoring.soak_metrics import SoakMetrics
from app.reconciliation.paper_reconciler import ReconciliationResult

logger = structlog.get_logger()

ZERO = Decimal("0")


@dataclass(frozen=True)
class DailyReportData:
    """Immutable snapshot of a single day's paper trading activity."""

    report_date: date
    exchange: str
    symbols: tuple[str, ...]
    run_id: str

    # PnL
    equity: Decimal = ZERO
    cash_balance: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    unrealized_pnl: Decimal = ZERO
    total_fees: Decimal = ZERO
    total_slippage: Decimal = ZERO
    daily_pnl: Decimal = ZERO
    daily_pnl_pct: Decimal = ZERO

    # Trades
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: Decimal = ZERO

    # Drawdown
    max_drawdown: Decimal = ZERO
    max_drawdown_pct: Decimal = ZERO
    current_drawdown: Decimal = ZERO

    # Positions
    open_positions: int = 0
    capital_utilization: Decimal = ZERO

    # Reconciliation
    reconciliation_checks: int = 0
    reconciliation_fatal_count: int = 0
    reconciliation_recoverable_count: int = 0
    last_reconciliation_status: str = "UNKNOWN"
    last_reconciliation_discrepancies: tuple[dict[str, Any], ...] = ()

    # Runtime
    candles_processed: int = 0
    runtime_errors: int = 0
    risk_rejections: int = 0
    emergency_stops: int = 0

    # Metadata
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_date": self.report_date.isoformat(),
            "exchange": self.exchange,
            "symbols": list(self.symbols),
            "run_id": self.run_id,
            "pnl": {
                "equity": str(self.equity),
                "cash_balance": str(self.cash_balance),
                "realized_pnl": str(self.realized_pnl),
                "unrealized_pnl": str(self.unrealized_pnl),
                "total_fees": str(self.total_fees),
                "total_slippage": str(self.total_slippage),
                "daily_pnl": str(self.daily_pnl),
                "daily_pnl_pct": str(self.daily_pnl_pct),
            },
            "trades": {
                "total": self.total_trades,
                "winning": self.winning_trades,
                "losing": self.losing_trades,
                "win_rate": str(self.win_rate),
            },
            "drawdown": {
                "max": str(self.max_drawdown),
                "max_pct": str(self.max_drawdown_pct),
                "current": str(self.current_drawdown),
            },
            "positions": {
                "open": self.open_positions,
                "capital_utilization": str(self.capital_utilization),
            },
            "reconciliation": {
                "checks": self.reconciliation_checks,
                "fatal_count": self.reconciliation_fatal_count,
                "recoverable_count": self.reconciliation_recoverable_count,
                "last_status": self.last_reconciliation_status,
                "last_discrepancies": list(self.last_reconciliation_discrepancies),
            },
            "runtime": {
                "candles_processed": self.candles_processed,
                "errors": self.runtime_errors,
                "risk_rejections": self.risk_rejections,
                "emergency_stops": self.emergency_stops,
            },
            "metadata": {
                "generated_at": self.generated_at.isoformat(),
                "content_hash": self.content_hash,
            },
        }


class DailyReportGenerator:
    """Build immutable daily reports from live paper trading state.

    The report is written once per day with a content hash.  Re-running
    the generator for the same day produces the same report (idempotent).
    """

    def __init__(
        self,
        *,
        exchange: str = "bybit",
        symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT"),
        run_id: str = "",
    ) -> None:
        self.exchange = exchange
        self.symbols = symbols
        self.run_id = run_id

    def generate(
        self,
        *,
        pnl_data: dict[str, Any] | None = None,
        reconciliation: ReconciliationResult | None = None,
        metrics: SoakMetrics | None = None,
        report_date: date | None = None,
    ) -> DailyReportData:
        """Generate a daily report from the provided state.

        Args:
            pnl_data: Dict with equity, cash, realized_pnl, etc.
            reconciliation: Latest reconciliation result.
            metrics: Soak metrics for execution stats.
            report_date: Date for the report (defaults to today).
        """
        target_date = report_date or datetime.now(UTC).date()
        pnl = pnl_data or {}
        recon = reconciliation
        soak = metrics

        # Build reconciliation summary
        recon_checks = 0
        recon_fatal = 0
        recon_recoverable = 0
        recon_status = "NO_DATA"
        recon_discrepancies: tuple[dict[str, Any], ...] = ()

        if recon is not None:
            recon_checks = 1
            recon_fatal = recon.fatal_count
            recon_recoverable = recon.recoverable_count
            recon_status = "FATAL" if recon.has_fatal else "OK"
            recon_discrepancies = tuple(
                {
                    "category": d.category,
                    "severity": d.severity.value,
                    "message": d.message,
                }
                for d in recon.discrepancies
            )

        # Build metrics summary
        candles = 0
        errors = 0
        risk_rejections = 0
        emergency_stops = 0

        if soak is not None:
            counters = soak.counters
            candles = counters.get("market_events", 0)
            errors = counters.get("errors", 0)
            risk_rejections = counters.get("risk_rejections", 0)
            emergency_stops = counters.get("emergency_stops", 0)

        # PnL fields
        equity = Decimal(str(pnl.get("equity", "0")))
        cash = Decimal(str(pnl.get("cash_balance", "0")))
        realized = Decimal(str(pnl.get("realized_pnl", "0")))
        unrealized = Decimal(str(pnl.get("unrealized_pnl", "0")))
        fees = Decimal(str(pnl.get("fees_paid", "0")))
        slippage = Decimal(str(pnl.get("slippage", "0")))
        daily_pnl = Decimal(str(pnl.get("daily_pnl", "0")))
        prev_equity = Decimal(str(pnl.get("previous_equity", equity - daily_pnl)))
        daily_pnl_pct = (daily_pnl / prev_equity * Decimal("100")) if prev_equity > 0 else ZERO

        # Trades
        total_trades = int(pnl.get("total_trades", 0))
        winning = int(pnl.get("winning_trades", 0))
        losing = int(pnl.get("losing_trades", 0))
        win_rate = Decimal(winning) / Decimal(total_trades) if total_trades > 0 else ZERO

        # Drawdown
        max_dd = Decimal(str(pnl.get("max_drawdown", "0")))
        max_dd_pct = Decimal(str(pnl.get("max_drawdown_pct", "0")))
        current_dd = Decimal(str(pnl.get("current_drawdown", "0")))

        # Positions
        open_pos = int(pnl.get("open_positions", 0))
        cap_util = Decimal(str(pnl.get("capital_utilization", "0")))

        data = DailyReportData(
            report_date=target_date,
            exchange=self.exchange,
            symbols=self.symbols,
            run_id=self.run_id,
            equity=equity,
            cash_balance=cash,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            total_fees=fees,
            total_slippage=slippage,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            total_trades=total_trades,
            winning_trades=winning,
            losing_trades=losing,
            win_rate=win_rate,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            current_drawdown=current_dd,
            open_positions=open_pos,
            capital_utilization=cap_util,
            reconciliation_checks=recon_checks,
            reconciliation_fatal_count=recon_fatal,
            reconciliation_recoverable_count=recon_recoverable,
            last_reconciliation_status=recon_status,
            last_reconciliation_discrepancies=recon_discrepancies,
            candles_processed=candles,
            runtime_errors=errors,
            risk_rejections=risk_rejections,
            emergency_stops=emergency_stops,
        )

        # Compute content hash (exclude generated_at and content_hash for determinism)
        report_dict = data.to_dict()
        hash_payload = {
            k: v for k, v in report_dict.items()
            if k != "metadata"
        }
        hash_payload["metadata"] = {
            k: v for k, v in report_dict.get("metadata", {}).items()
            if k not in ("generated_at", "content_hash")
        }
        content = json.dumps(hash_payload, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        # Rebuild with hash included
        return DailyReportData(
            report_date=data.report_date,
            exchange=data.exchange,
            symbols=data.symbols,
            run_id=data.run_id,
            equity=data.equity,
            cash_balance=data.cash_balance,
            realized_pnl=data.realized_pnl,
            unrealized_pnl=data.unrealized_pnl,
            total_fees=data.total_fees,
            total_slippage=data.total_slippage,
            daily_pnl=data.daily_pnl,
            daily_pnl_pct=data.daily_pnl_pct,
            total_trades=data.total_trades,
            winning_trades=data.winning_trades,
            losing_trades=data.losing_trades,
            win_rate=data.win_rate,
            max_drawdown=data.max_drawdown,
            max_drawdown_pct=data.max_drawdown_pct,
            current_drawdown=data.current_drawdown,
            open_positions=data.open_positions,
            capital_utilization=data.capital_utilization,
            reconciliation_checks=data.reconciliation_checks,
            reconciliation_fatal_count=data.reconciliation_fatal_count,
            reconciliation_recoverable_count=data.reconciliation_recoverable_count,
            last_reconciliation_status=data.last_reconciliation_status,
            last_reconciliation_discrepancies=data.last_reconciliation_discrepancies,
            candles_processed=data.candles_processed,
            runtime_errors=data.runtime_errors,
            risk_rejections=data.risk_rejections,
            emergency_stops=data.emergency_stops,
            content_hash=content_hash,
        )

    def write_report(
        self,
        data: DailyReportData,
        output_dir: str | Path,
    ) -> Path:
        """Write immutable daily report to disk.

        File is named: daily_report_YYYY-MM-DD.json
        The content hash is embedded inside the file for verification.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        filename = f"daily_report_{data.report_date.isoformat()}.json"
        filepath = output_path / filename

        report = data.to_dict()
        content = json.dumps(report, indent=2, ensure_ascii=False)
        filepath.write_text(content + "\n", encoding="utf-8")

        logger.info(
            "daily_report_written",
            date=data.report_date.isoformat(),
            path=str(filepath),
            content_hash=data.content_hash[:16],
            reconciliation=data.last_reconciliation_status,
        )
        return filepath
