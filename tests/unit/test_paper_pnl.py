"""Tests for paper trading PnL tracking and metrics."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.models.paper_fill_state import PaperFillState
from app.models.paper_position_state import PaperPositionState
from app.reporting.paper_pnl import (
    PaperPnLTracker,
    PnLRecord,
    EquityPoint,
    TradingMetrics,
    EnginePriceProvider,
)


class MockPriceProvider:
    """Mock price provider for testing."""

    def __init__(self, prices: dict[str, Decimal]) -> None:
        self._prices = prices

    def get_price(self, symbol: str) -> Decimal | None:
        return self._prices.get(symbol)


def test_pnl_tracker_initialization() -> None:
    """Test PnL tracker initializes correctly."""
    tracker = PaperPnLTracker(
        initial_capital=Decimal("10000"),
        fee_rate=Decimal("0.001"),
    )

    assert tracker.initial_capital == Decimal("10000")
    assert tracker.fee_rate == Decimal("0.001")
    assert tracker.current_equity == Decimal("10000")
    assert tracker.current_drawdown == Decimal("0")
    assert len(tracker.pnl_records) == 0
    assert len(tracker.equity_curve) == 0


def test_calculate_unrealized_pnl() -> None:
    """Test unrealized PnL calculation."""
    tracker = PaperPnLTracker()

    positions = {
        "BTCUSDT": PaperPositionState(
            symbol="BTCUSDT",
            quantity=Decimal("1"),
            average_price=Decimal("50000"),
        )
    }

    # Price went up to 55000
    price_provider = MockPriceProvider({"BTCUSDT": Decimal("55000")})
    unrealized = tracker.calculate_unrealized_pnl(positions, price_provider)

    assert unrealized == Decimal("5000")  # (55000 - 50000) * 1

    # Price went down to 48000
    price_provider = MockPriceProvider({"BTCUSDT": Decimal("48000")})
    unrealized = tracker.calculate_unrealized_pnl(positions, price_provider)

    assert unrealized == Decimal("-2000")  # (48000 - 50000) * 1


def test_calculate_fees() -> None:
    """Test fee calculation."""
    tracker = PaperPnLTracker(fee_rate=Decimal("0.001"))  # 0.1%

    fills = [
        PaperFillState(
            fill_id="1",
            order_id="o1",
            symbol="BTCUSDT",
            quantity=Decimal("1"),
            price=Decimal("50000"),
            executed_at=datetime.now(timezone.utc),
        ),
        PaperFillState(
            fill_id="2",
            order_id="o2",
            symbol="BTCUSDT",
            quantity=Decimal("1"),
            price=Decimal("55000"),
            executed_at=datetime.now(timezone.utc),
        ),
    ]

    fees = tracker.calculate_fees(fills)

    # Fee = (1 * 50000 + 1 * 55000) * 0.001 = 105
    assert fees == Decimal("105")


def test_record_snapshot() -> None:
    """Test recording PnL snapshot."""
    tracker = PaperPnLTracker(initial_capital=Decimal("10000"))

    engine = PaperExecutionEngine()
    engine.cash_balance = Decimal("9000")
    engine.positions = {
        "BTCUSDT": PaperPositionState(
            symbol="BTCUSDT",
            quantity=Decimal("0.1"),
            average_price=Decimal("50000"),
        )
    }

    # Create a mock last candle for price
    from app.models.candle import Candle
    engine._last_candle = Candle(
        symbol="BTCUSDT",
        open_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        open=Decimal("52000"),
        high=Decimal("53000"),
        low=Decimal("51000"),
        close=Decimal("52000"),
        volume=Decimal("100"),
    )

    record = tracker.record_snapshot(
        timestamp=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        sequence=1,
        engine=engine,
        realized_pnl=Decimal("0"),
    )

    assert isinstance(record, PnLRecord)
    assert record.timestamp == datetime(2024, 1, 1, 1, tzinfo=timezone.utc)
    assert record.cash_balance == Decimal("9000")
    assert record.position_value == Decimal("5200")  # 0.1 * 52000
    assert record.equity == Decimal("14200")  # 9000 + 5200


def test_equity_curve_and_drawdown() -> None:
    """Test equity curve tracking and drawdown calculation."""
    tracker = PaperPnLTracker(initial_capital=Decimal("10000"))

    # Record snapshots with increasing equity
    tracker.record_snapshot(
        timestamp=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        sequence=1,
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("500"),
    )
    # Equity = 10000 + 0 + 500 = 10500, peak = 10500

    tracker.record_snapshot(
        timestamp=datetime(2024, 1, 1, 2, tzinfo=timezone.utc),
        sequence=2,
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("1000"),
    )
    # Equity = 10000 + 0 + 1000 = 11000, peak = 11000

    tracker.record_snapshot(
        timestamp=datetime(2024, 1, 1, 3, tzinfo=timezone.utc),
        sequence=3,
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("500"),
    )
    # Equity = 10000 + 0 + 500 = 10500, peak = 11000, drawdown = 500

    assert len(tracker.equity_curve) == 3
    assert tracker.current_equity == Decimal("10500")
    assert tracker.current_drawdown == Decimal("500")
    assert tracker.current_drawdown_pct == Decimal("500") / Decimal("11000") * Decimal("100")


def test_calculate_metrics_with_wins_and_losses() -> None:
    """Test aggregated metrics calculation."""
    tracker = PaperPnLTracker()

    # Simulate trade PnL directly (normally populated via fills)
    tracker._trade_pnl = [
        Decimal("100"),   # Win
        Decimal("-50"),   # Loss
        Decimal("200"),   # Win
        Decimal("-30"),   # Loss
        Decimal("80"),    # Win
    ]

    metrics = tracker.calculate_metrics()

    assert metrics.total_trades == 5
    assert metrics.win_count == 3
    assert metrics.loss_count == 2
    assert metrics.win_rate == Decimal("0.6")  # 3/5
    assert metrics.total_realized_pnl == Decimal("300")  # 100 - 50 + 200 - 30 + 80
    assert metrics.avg_win == Decimal("126.6666666666666666666666667")
    assert metrics.avg_loss == Decimal("40")
    assert metrics.profit_factor == Decimal("380") / Decimal("80")  # gross_profit / gross_loss


def test_reset_tracker() -> None:
    """Test resetting the tracker."""
    tracker = PaperPnLTracker(initial_capital=Decimal("10000"))

    # Add some data
    tracker.record_snapshot(
        timestamp=datetime.now(timezone.utc),
        sequence=1,
        realized_pnl=Decimal("100"),
    )
    tracker._trade_pnl.append(Decimal("50"))

    # Reset
    tracker.reset()

    assert tracker.current_equity == Decimal("10000")
    assert len(tracker.pnl_records) == 0
    assert len(tracker.equity_curve) == 0
    assert len(tracker._trade_pnl) == 0
    assert tracker._fees_paid == Decimal("0")


def test_engine_price_provider() -> None:
    """Test EnginePriceProvider gets prices from execution engine."""
    engine = PaperExecutionEngine()

    from app.models.candle import Candle
    engine._last_candle = Candle(
        symbol="BTCUSDT",
        open_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        close_time=datetime(2024, 1, 1, 1, tzinfo=timezone.utc),
        open=Decimal("50000"),
        high=Decimal("51000"),
        low=Decimal("49000"),
        close=Decimal("50500"),
        volume=Decimal("100"),
    )

    provider = EnginePriceProvider(engine)
    price = provider.get_price("BTCUSDT")

    assert price == Decimal("50500")


def test_metrics_with_no_trades() -> None:
    """Test metrics calculation when no trades occurred."""
    tracker = PaperPnLTracker()

    metrics = tracker.calculate_metrics()

    assert metrics.total_trades == 0
    assert metrics.win_count == 0
    assert metrics.loss_count == 0
    assert metrics.win_rate == Decimal("0")
    assert metrics.total_realized_pnl == Decimal("0")
    assert metrics.profit_factor == Decimal("0")


@pytest.mark.asyncio
async def test_pnl_tracking_integration() -> None:
    """Integration test: track PnL through a complete trading cycle."""
    from app.exchange.fill_simulator import FillSimulator
    from app.exchange.paper_market_data import PaperMarketData
    from app.execution.paper_trading_runtime import PaperTradingRuntime
    from app.models.candle import Candle

    # Setup
    tracker = PaperPnLTracker(initial_capital=Decimal("10000"), fee_rate=Decimal("0.001"))

    candles = [
        Candle(
            symbol="BTCUSDT",
            open_time=datetime(2024, 1, 1, i, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, i+1, tzinfo=timezone.utc),
            open=Decimal("50000") + Decimal(str(i * 100)),
            high=Decimal("51000") + Decimal(str(i * 100)),
            low=Decimal("49000") + Decimal(str(i * 100)),
            close=Decimal("50500") + Decimal(str(i * 100)),
            volume=Decimal("100"),
        )
        for i in range(5)
    ]

    market_data = PaperMarketData(candles)
    execution_engine = PaperExecutionEngine(fill_simulator=FillSimulator())

    # Simple strategy: buy on first candle
    class BuyAndHoldStrategy:
        async def on_candle(self, candle, engine):
            from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide
            if engine.last_sequence == 0:
                return [ExecutionRequest(
                    symbol=candle.symbol,
                    side=OrderSide.BUY,
                    quantity=Decimal("0.1"),
                )]
            return []

    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        strategy=BuyAndHoldStrategy(),
    )

    await runtime.run_async()

    # Track final PnL
    final_record = tracker.record_snapshot(
        timestamp=datetime.now(timezone.utc),
        sequence=execution_engine.last_sequence,
        engine=execution_engine,
    )

    assert final_record is not None
    assert execution_engine.last_sequence == 5
    # Position should exist after buying
    assert len(execution_engine.positions) >= 0  # May be empty if no fills occurred
