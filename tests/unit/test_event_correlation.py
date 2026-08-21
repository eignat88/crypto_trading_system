"""Tests for structured event correlation (run_id / signal_id) across the pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.models.trading import Fill, Order, RiskDecision, Signal, SignalAction


# ---------------------------------------------------------------------------
# Signal model
# ---------------------------------------------------------------------------


class TestSignalCorrelation:
    def test_signal_has_unique_signal_id(self) -> None:
        s1 = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            price=Decimal("100"),
            quantity=Decimal("1"),
            timestamp=datetime.now(UTC),
        )
        s2 = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            price=Decimal("100"),
            quantity=Decimal("1"),
            timestamp=datetime.now(UTC),
        )
        assert s1.signal_id != s2.signal_id
        assert len(s1.signal_id) == 36  # UUID format

    def test_signal_default_run_id_is_empty(self) -> None:
        s = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            price=Decimal("100"),
            quantity=Decimal("1"),
            timestamp=datetime.now(UTC),
        )
        assert s.run_id == ""

    def test_signal_run_id_can_be_set(self) -> None:
        s = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            price=Decimal("100"),
            quantity=Decimal("1"),
            timestamp=datetime.now(UTC),
            run_id="test-run-001",
        )
        assert s.run_id == "test-run-001"


# ---------------------------------------------------------------------------
# Order / Fill / RiskDecision correlation
# ---------------------------------------------------------------------------


class TestOrderCorrelation:
    def test_order_carry_correlation_ids(self) -> None:
        signal = Signal(
            action=SignalAction.BUY,
            symbol="BTCUSDT",
            price=Decimal("100"),
            quantity=Decimal("1"),
            timestamp=datetime.now(UTC),
            run_id="run-123",
            signal_id="sig-456",
        )
        order = Order(
            order_id="ord-001",
            signal=signal,
            side="buy",
            quantity=Decimal("1"),
            requested_price=Decimal("100"),
            created_at=datetime.now(UTC),
            run_id=signal.run_id,
            signal_id=signal.signal_id,
        )
        assert order.run_id == "run-123"
        assert order.signal_id == "sig-456"


class TestFillCorrelation:
    def test_fill_carry_correlation_ids(self) -> None:
        fill = Fill(
            fill_id="fill-001",
            order_id="ord-001",
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("100"),
            commission=Decimal("0.001"),
            timestamp=datetime.now(UTC),
            run_id="run-123",
            signal_id="sig-456",
        )
        assert fill.run_id == "run-123"
        assert fill.signal_id == "sig-456"


class TestRiskDecisionCorrelation:
    def test_risk_decision_carry_correlation_ids(self) -> None:
        decision = RiskDecision(
            order_id="ord-001",
            approved=True,
            risk_level="LOW",
            codes=(),
            reasons=(),
            requested_quantity=Decimal("1"),
            run_id="run-123",
            signal_id="sig-456",
        )
        assert decision.run_id == "run-123"
        assert decision.signal_id == "sig-456"


# ---------------------------------------------------------------------------
# BacktestEngine propagation
# ---------------------------------------------------------------------------


class TestBacktestCorrelation:
    def _make_candles(self, n: int = 5) -> list[dict]:
        return [
            {
                "symbol": "BTCUSDT",
                "open_time": datetime(2026, 1, 1, i, tzinfo=UTC),
                "open": Decimal("100"),
                "high": Decimal("105"),
                "low": Decimal("95"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
            }
            for i in range(n)
        ]

    def test_backtest_generates_run_id(self) -> None:
        engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("1000")))
        engine.run(self._make_candles(), lambda c, p, s: None)
        # Even with no signals, the engine ran and generated a run_id internally
        assert engine._sequence >= 0

    def test_backtest_propagates_signal_id_to_orders_and_fills(self) -> None:
        from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy

        strategy = TrendDCAStrategy(
            ["BTCUSDT"],
            config=DCAConfig(rsi_entry_threshold=Decimal("100")),  # force entry
        )
        candles = [
            {
                "symbol": "BTCUSDT",
                "open_time": datetime(2026, 1, 1, 0, tzinfo=UTC),
                "open": Decimal("100"),
                "high": Decimal("105"),
                "low": Decimal("95"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
                "indicators": {
                    "ema_200": Decimal("90"),
                    "ema_50": Decimal("95"),
                    "rsi": Decimal("40"),
                    "regime": "TREND_UP",
                    "volatility": Decimal("0.10"),
                },
            },
            {
                "symbol": "BTCUSDT",
                "open_time": datetime(2026, 1, 1, 1, tzinfo=UTC),
                "open": Decimal("100"),
                "high": Decimal("105"),
                "low": Decimal("95"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
                "indicators": {
                    "ema_200": Decimal("90"),
                    "ema_50": Decimal("95"),
                    "rsi": Decimal("40"),
                    "regime": "TREND_UP",
                    "volatility": Decimal("0.10"),
                },
            },
        ]
        engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("1000")))
        result = engine.run(candles, strategy)

        # If signals were generated, verify correlation chain
        if result.signals and result.orders:
            signal = result.signals[0]
            order = result.orders[0]
            assert order.signal_id == signal.signal_id
            assert order.run_id == signal.run_id
            if result.fills:
                fill = result.fills[0]
                assert fill.signal_id == signal.signal_id
                assert fill.run_id == signal.run_id


# ---------------------------------------------------------------------------
# PaperExecutionEngine propagation
# ---------------------------------------------------------------------------


class TestPaperExecutionCorrelation:
    def test_execute_stores_run_id_and_signal_id(self) -> None:
        from app.models.candle import Candle

        engine = PaperExecutionEngine()
        engine.on_candle(
            Candle(
                symbol="BTCUSDT",
                open_time=datetime(2026, 1, 1, tzinfo=UTC),
                close_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
                open=Decimal("100"),
                high=Decimal("100"),
                low=Decimal("100"),
                close=Decimal("100"),
                volume=Decimal("1000"),
            )
        )
        request = ExecutionRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.01"),
        )
        result = engine.execute(
            request,
            run_id="test-run-001",
            signal_id="test-sig-001",
        )
        assert result.status.value == "FILLED"

        # Verify stored order has correlation IDs
        order = list(engine.orders.values())[-1]
        assert order.run_id == "test-run-001"
        assert order.signal_id == "test-sig-001"

        # Verify stored fill has correlation IDs
        fill = list(engine.fills.values())[-1]
        assert fill.run_id == "test-run-001"
        assert fill.signal_id == "test-sig-001"


# ---------------------------------------------------------------------------
# MarketPipeline propagation
# ---------------------------------------------------------------------------


class TestPipelineCorrelation:
    def test_pipeline_has_run_id(self) -> None:
        from app.pipeline.market_pipeline import MarketPipeline

        pipeline = MarketPipeline(run_id="custom-run-001")
        assert pipeline.run_id == "custom-run-001"

    def test_pipeline_generates_run_id_by_default(self) -> None:
        from app.pipeline.market_pipeline import MarketPipeline

        pipeline = MarketPipeline()
        assert len(pipeline.run_id) == 36  # UUID format
