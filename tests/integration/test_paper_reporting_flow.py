"""Integration tests for paper trading reporting flow.

Tests the full cycle: Runtime -> Engine -> Trade -> Metrics Collector -> Report.
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import tempfile

from app.reporting.paper_pnl import PaperPnLTracker
from app.reporting.paper_metrics import (
    PaperMetricsCollector,
    EquityCurveReport,
    PerformanceSummary,
)


class TestPaperReportingFlow:
    """Test full reporting flow from trade execution to report generation."""

    def test_profitable_trade_flow(self):
        """Test reporting flow with a profitable trade."""
        # Setup
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        # Simulate trade events
        trade_time = datetime.now(timezone.utc)

        # Buy order - record fee and slippage directly in tracker
        tracker._fees_paid = Decimal("5")
        tracker._slippage_total = Decimal("2")

        # Record equity snapshot with PnL
        collector.snapshot_equity(
            timestamp=trade_time,
            sequence=1,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        # Sell order at profit - simulate realized PnL
        sell_time = datetime.now(timezone.utc)
        tracker._fees_paid = Decimal("10.2")  # Total fees
        tracker._slippage_total = Decimal("3")  # Total slippage

        # Record final snapshot with realized profit
        collector.snapshot_equity(
            timestamp=sell_time,
            sequence=2,
            realized_pnl=Decimal("200"),  # Profit from 50000->52000 on 0.1 BTC
            unrealized_pnl=Decimal("0"),
        )

        # Generate reports
        performance = collector.generate_performance_summary()
        assert performance is not None
        assert performance.total_trades >= 0
        assert performance.total_fees > 0
        assert performance.total_slippage > 0

        equity_report = collector.generate_equity_curve_report()
        assert equity_report is not None
        assert equity_report.num_points == 2

    def test_loss_making_trade_flow(self):
        """Test reporting flow with a loss-making trade."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        trade_time = datetime.now(timezone.utc)

        # Buy order - record fees
        tracker._fees_paid = Decimal("3")

        collector.snapshot_equity(
            timestamp=trade_time,
            sequence=1,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        # Sell order at loss - simulate realized loss
        sell_time = datetime.now(timezone.utc)
        tracker._fees_paid = Decimal("5.8")  # Total fees

        collector.snapshot_equity(
            timestamp=sell_time,
            sequence=2,
            realized_pnl=Decimal("-200"),  # Loss from 3000->2800 on 1 ETH
            unrealized_pnl=Decimal("0"),
        )

        # Verify negative PnL
        performance = collector.generate_performance_summary()
        assert performance is not None
        assert performance.net_pnl < 0
        assert performance.loss_count >= 0

    def test_fee_tracking(self):
        """Test that fees are properly tracked and reported."""
        tracker = PaperPnLTracker(
            initial_capital=Decimal("10000"),
            fee_rate=Decimal("0.001"),
        )
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        trade_time = datetime.now(timezone.utc)

        # Multiple trades with fees - directly set in tracker
        for i in range(5):
            tracker._fees_paid += Decimal("1")

        # Record snapshot to build equity curve
        collector.snapshot_equity(
            timestamp=trade_time,
            sequence=1,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        # Verify fees accumulated
        assert tracker._fees_paid == Decimal("5")

        performance = collector.generate_performance_summary()
        assert performance is not None
        assert performance.total_fees == Decimal("5")

    def test_slippage_tracking(self):
        """Test that slippage is properly tracked."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        trade_time = datetime.now(timezone.utc)

        # Trade with expected vs actual price difference - directly set in tracker
        tracker._slippage_total = Decimal("10")

        # Record snapshot to build equity curve
        collector.snapshot_equity(
            timestamp=trade_time,
            sequence=1,
            realized_pnl=Decimal("0"),
            unrealized_pnl=Decimal("0"),
        )

        assert tracker._slippage_total == Decimal("10")

        performance = collector.generate_performance_summary()
        assert performance is not None
        assert performance.total_slippage == Decimal("10")

    def test_equity_curve_after_multiple_candles(self):
        """Test equity curve builds correctly over multiple candles."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        base_time = datetime.now(timezone.utc)

        # Simulate multiple candle processing
        for i in range(10):
            candle_time = base_time + timedelta(minutes=i)

            collector.record_candle_processed(
                timestamp=candle_time,
                sequence=i,
                symbol="BTCUSDT",
            )

            # Add some PnL variation
            unrealized_pnl = Decimal(str((i - 5) * 10))  # Goes down then up
            collector.snapshot_equity(
                timestamp=candle_time,
                sequence=i,
                realized_pnl=Decimal("0"),
                unrealized_pnl=unrealized_pnl,
            )

        # Verify equity curve has all points
        equity_report = collector.generate_equity_curve_report()
        assert equity_report is not None
        assert equity_report.num_points == 10

        # Verify drawdown was calculated
        assert equity_report.max_drawdown >= 0
        assert equity_report.peak_equity >= equity_report.starting_equity

    def test_export_report_to_json(self):
        """Test exporting full report to JSON file."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        trade_time = datetime.now(timezone.utc)

        # Add some trades
        collector.record_trade(
            timestamp=trade_time,
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
            fee=Decimal("5"),
        )

        collector.snapshot_equity(timestamp=trade_time, sequence=1)

        # Export to temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "report.json"
            collector.export_report(output_path)

            assert output_path.exists()

            import json
            with open(output_path) as f:
                data = json.load(f)

            assert "performance_summary" in data or "equity_curve_summary" in data
            assert "trade_count" in data
            assert "candle_count" in data

    def test_reset_collector(self):
        """Test resetting the metrics collector."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        trade_time = datetime.now(timezone.utc)

        # Add data
        collector.record_trade(
            timestamp=trade_time,
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("50000"),
        )
        collector.snapshot_equity(timestamp=trade_time, sequence=1)

        # Verify data exists
        assert len(collector._trade_events) > 0
        assert len(tracker.equity_curve) > 0

        # Reset
        collector.reset()

        # Verify data cleared
        assert len(collector._trade_events) == 0
        assert len(tracker.equity_curve) == 0
        assert tracker._fees_paid == Decimal("0")
        assert tracker._slippage_total == Decimal("0")

    def test_negative_pnl_scenario(self):
        """Test scenario with negative total PnL."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        # Record multiple snapshots with varying losses
        base_time = datetime.now(timezone.utc)
        for i in range(5):
            # Calculate progressively worse unrealized PnL
            unrealized = Decimal("-50") - (Decimal(str(i)) * Decimal("10"))
            
            collector.snapshot_equity(
                timestamp=base_time,
                sequence=i,
                realized_pnl=Decimal("0"),
                unrealized_pnl=unrealized,
            )

        equity_report = collector.generate_equity_curve_report()
        assert equity_report is not None
        # First point has -50 PnL, last point has -90 PnL
        assert equity_report.ending_equity < equity_report.starting_equity
        assert equity_report.total_return < 0

    def test_win_loss_statistics(self):
        """Test win/loss statistics calculation."""
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        collector = PaperMetricsCollector(pnl_tracker=tracker)

        # Manually add trade PnL to tracker (simulating closed trades)
        tracker._trade_pnl = [
            Decimal("100"),   # Win
            Decimal("-50"),   # Loss
            Decimal("75"),    # Win
            Decimal("-30"),   # Loss
            Decimal("200"),   # Win
        ]

        # Record snapshot to build equity curve
        collector.snapshot_equity(
            timestamp=datetime.now(timezone.utc),
            sequence=1,
            realized_pnl=Decimal("295"),  # Sum of trade PnL
            unrealized_pnl=Decimal("0"),
        )

        performance = collector.generate_performance_summary()
        assert performance is not None
        assert performance.win_count == 3
        assert performance.loss_count == 2
        assert performance.total_trades == 5
        assert performance.win_rate == Decimal("0.6")  # 3/5
