"""Paper trading metrics and reporting.

This module provides reporting interfaces for paper trading performance,
including equity curve reports and performance summaries.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.reporting.paper_pnl import (
    PaperPnLTracker,
    PnLRecord,
    EquityPoint,
    TradingMetrics,
)


logger = logging.getLogger(__name__)


@dataclass
class EquityCurveReport:
    """Report on equity curve performance."""

    start_date: datetime
    end_date: datetime
    starting_equity: Decimal
    ending_equity: Decimal
    peak_equity: Decimal
    trough_equity: Decimal
    total_return: Decimal
    total_return_pct: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    num_points: int
    equity_points: list[EquityPoint]

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "starting_equity": str(self.starting_equity),
            "ending_equity": str(self.ending_equity),
            "peak_equity": str(self.peak_equity),
            "trough_equity": str(self.trough_equity),
            "total_return": str(self.total_return),
            "total_return_pct": str(self.total_return_pct),
            "max_drawdown": str(self.max_drawdown),
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "num_points": self.num_points,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert report to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


@dataclass
class PerformanceSummary:
    """Summary of trading performance."""

    period_start: datetime
    period_end: datetime
    initial_capital: Decimal
    final_equity: Decimal
    total_realized_pnl: Decimal
    total_unrealized_pnl: Decimal
    total_fees: Decimal
    total_slippage: Decimal
    net_pnl: Decimal
    net_pnl_pct: Decimal
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: Decimal
    avg_win: Decimal
    avg_loss: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    sharpe_ratio: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert summary to dictionary."""
        return {
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "initial_capital": str(self.initial_capital),
            "final_equity": str(self.final_equity),
            "total_realized_pnl": str(self.total_realized_pnl),
            "total_unrealized_pnl": str(self.total_unrealized_pnl),
            "total_fees": str(self.total_fees),
            "total_slippage": str(self.total_slippage),
            "net_pnl": str(self.net_pnl),
            "net_pnl_pct": str(self.net_pnl_pct),
            "total_trades": self.total_trades,
            "win_count": self.win_count,
            "loss_count": self.loss_count,
            "win_rate": str(self.win_rate),
            "avg_win": str(self.avg_win),
            "avg_loss": str(self.avg_loss),
            "profit_factor": str(self.profit_factor),
            "max_drawdown": str(self.max_drawdown),
            "max_drawdown_pct": str(self.max_drawdown_pct),
            "sharpe_ratio": str(self.sharpe_ratio) if self.sharpe_ratio else None,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert summary to JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


class PaperMetricsCollector:
    """Collect and aggregate metrics from PaperExecutionEngine.

    This collector listens to trade events from the execution engine
    and aggregates them into performance reports.
    """

    def __init__(
        self,
        pnl_tracker: PaperPnLTracker,
    ) -> None:
        self.pnl_tracker = pnl_tracker
        self._trade_events: list[dict[str, Any]] = []
        self._candle_events: list[dict[str, Any]] = []

    def record_trade(
        self,
        timestamp: datetime,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        fee: Decimal = Decimal("0"),
        slippage: Decimal = Decimal("0"),
        expected_price: Decimal | None = None,
    ) -> None:
        """Record a trade event.

        Args:
            timestamp: Time of trade
            symbol: Trading pair symbol
            side: 'buy' or 'sell'
            quantity: Trade quantity
            price: Execution price
            fee: Commission fee
            slippage: Price slippage
            expected_price: Expected price before execution
        """
        event = {
            "timestamp": timestamp,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "fee": fee,
            "slippage": slippage,
            "expected_price": expected_price,
        }
        self._trade_events.append(event)

        # Update tracker fees and slippage
        if fee > 0:
            self.pnl_tracker._fees_paid += fee
        if slippage > 0:
            self.pnl_tracker._slippage_total += slippage

        logger.debug(
            f"Trade recorded: {side} {quantity} {symbol} @ {price}, fee={fee}, slippage={slippage}"
        )

    def record_candle_processed(
        self,
        timestamp: datetime,
        sequence: int,
        symbol: str,
    ) -> None:
        """Record a candle processing event.

        Args:
            timestamp: Candle timestamp
            sequence: Market event sequence number
            symbol: Trading pair symbol
        """
        event = {
            "timestamp": timestamp,
            "sequence": sequence,
            "symbol": symbol,
        }
        self._candle_events.append(event)
        logger.debug(f"Candle processed: {symbol} #{sequence} @ {timestamp}")

    def snapshot_equity(
        self,
        timestamp: datetime | None = None,
        sequence: int = 0,
        realized_pnl: Decimal | None = None,
        unrealized_pnl: Decimal | None = None,
    ) -> PnLRecord:
        """Take a snapshot of current equity state.

        Args:
            timestamp: Time of snapshot (defaults to now)
            sequence: Market event sequence number
            realized_pnl: Pre-calculated realized PnL
            unrealized_pnl: Pre-calculated unrealized PnL

        Returns:
            PnLRecord with current metrics
        """
        return self.pnl_tracker.record_snapshot(
            timestamp=timestamp,
            sequence=sequence,
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
        )

    def generate_equity_curve_report(self) -> EquityCurveReport | None:
        """Generate equity curve report.

        Returns:
            EquityCurveReport or None if no data
        """
        equity_points = self.pnl_tracker.equity_curve
        if not equity_points:
            return None

        start_point = equity_points[0]
        end_point = equity_points[-1]

        starting_equity = start_point.equity
        ending_equity = end_point.equity
        total_return = ending_equity - starting_equity
        total_return_pct = (
            (total_return / starting_equity * Decimal("100"))
            if starting_equity > 0
            else Decimal("0")
        )

        peak_equity = max(p.equity for p in equity_points)
        trough_equity = min(p.equity for p in equity_points)

        # Calculate maximum drawdown properly from all equity points
        max_drawdown = Decimal("0")
        max_drawdown_pct = Decimal("0")
        running_peak = starting_equity
        
        for point in equity_points:
            if point.equity > running_peak:
                running_peak = point.equity
            drawdown = running_peak - point.equity
            drawdown_pct = (drawdown / running_peak * Decimal("100")) if running_peak > 0 else Decimal("0")
            
            if drawdown > max_drawdown:
                max_drawdown = drawdown
            if drawdown_pct > max_drawdown_pct:
                max_drawdown_pct = drawdown_pct

        return EquityCurveReport(
            start_date=start_point.timestamp,
            end_date=end_point.timestamp,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            peak_equity=peak_equity,
            trough_equity=trough_equity,
            total_return=total_return,
            total_return_pct=total_return_pct,
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            num_points=len(equity_points),
            equity_points=equity_points,
        )

    def generate_performance_summary(self) -> PerformanceSummary | None:
        """Generate performance summary report.

        Returns:
            PerformanceSummary or None if no data
        """
        metrics = self.pnl_tracker.calculate_metrics()
        equity_curve = self.pnl_tracker.equity_curve

        if not equity_curve:
            return None

        start_point = equity_curve[0]
        end_point = equity_curve[-1]

        initial_capital = self.pnl_tracker.initial_capital
        final_equity = end_point.equity
        net_pnl = final_equity - initial_capital
        net_pnl_pct = (
            (net_pnl / initial_capital * Decimal("100"))
            if initial_capital > 0
            else Decimal("0")
        )

        return PerformanceSummary(
            period_start=start_point.timestamp,
            period_end=end_point.timestamp,
            initial_capital=initial_capital,
            final_equity=final_equity,
            total_realized_pnl=metrics.total_realized_pnl,
            total_unrealized_pnl=metrics.total_unrealized_pnl,
            total_fees=metrics.total_fees,
            total_slippage=metrics.total_slippage,
            net_pnl=net_pnl,
            net_pnl_pct=net_pnl_pct,
            total_trades=metrics.total_trades,
            win_count=metrics.win_count,
            loss_count=metrics.loss_count,
            win_rate=metrics.win_rate,
            avg_win=metrics.avg_win,
            avg_loss=metrics.avg_loss,
            profit_factor=metrics.profit_factor,
            max_drawdown=metrics.max_drawdown,
            max_drawdown_pct=metrics.max_drawdown_pct,
        )

    def export_report(
        self,
        output_path: Path,
        include_equity_curve: bool = True,
    ) -> None:
        """Export full report to JSON file.

        Args:
            output_path: Path to output file
            include_equity_curve: Whether to include detailed equity curve
        """
        report_data: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        performance = self.generate_performance_summary()
        if performance:
            report_data["performance_summary"] = performance.to_dict()

        if include_equity_curve:
            equity_report = self.generate_equity_curve_report()
            if equity_report:
                report_data["equity_curve_summary"] = equity_report.to_dict()
                # Include last N points for brevity
                report_data["recent_equity_points"] = [
                    asdict(p) for p in equity_report.equity_points[-100:]
                ]

        report_data["trade_count"] = len(self._trade_events)
        report_data["candle_count"] = len(self._candle_events)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        logger.info(f"Report exported to {output_path}")

    def reset(self) -> None:
        """Reset all collected data."""
        self._trade_events.clear()
        self._candle_events.clear()
        self.pnl_tracker.reset()
        logger.info("Metrics collector reset")
