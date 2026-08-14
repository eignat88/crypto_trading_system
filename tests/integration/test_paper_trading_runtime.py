"""Integration tests for PaperTradingRuntime with state recovery."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.exchange.fill_simulator import FillSimulator
from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.execution.paper_trading_runtime import PaperTradingRuntime, DefaultRiskManager
from app.models.candle import Candle
from app.models.paper_state import PaperRuntimeState


class InMemoryPaperStateRepository:
    """In-memory implementation of PaperStateRepository for testing."""

    def __init__(self) -> None:
        self._state: PaperRuntimeState | None = None
        self._positions: dict[str, any] = {}
        self._orders: list[any] = []
        self._fills: list[any] = []

    async def save_state(self, state: PaperRuntimeState) -> None:
        self._state = state

    async def load_state(self) -> PaperRuntimeState | None:
        return self._state

    async def save_position(self, position) -> None:
        self._positions[position.symbol] = position

    async def load_positions(self):
        return list(self._positions.values())

    async def save_order(self, order) -> None:
        self._orders.append(order)

    async def save_fill(self, fill) -> None:
        self._fills.append(fill)


def create_test_candles(symbol: str = "BTCUSDT", count: int = 10, start_time: datetime | None = None) -> list[Candle]:
    """Create a list of test candles."""
    if start_time is None:
        start_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    candles = []
    base_price = Decimal("50000")
    
    for i in range(count):
        open_time = start_time + timedelta(hours=i)
        close_time = open_time + timedelta(hours=1)
        
        # Simple price movement
        price_change = Decimal(str((i % 5) - 2)) * Decimal("100")
        open_price = base_price + price_change
        close_price = open_price + Decimal(str((i % 3) - 1)) * Decimal("50")
        high_price = max(open_price, close_price) + Decimal("25")
        low_price = min(open_price, close_price) - Decimal("25")
        
        candles.append(Candle(
            symbol=symbol,
            open_time=open_time,
            close_time=close_time,
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=Decimal("100"),
        ))
    
    return candles


class SimpleTestStrategy:
    """Simple strategy that buys on first candle and sells on fifth."""

    def __init__(self, buy_at: int = 1, sell_at: int = 5) -> None:
        self.buy_at = buy_at
        self.sell_at = sell_at
        self._candles_seen = 0

    async def on_candle(self, candle, engine):
        from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide
        
        self._candles_seen += 1
        requests = []

        if self._candles_seen == self.buy_at:
            # Buy on first candle
            requests.append(ExecutionRequest(
                symbol=candle.symbol,
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
            ))
        elif self._candles_seen == self.sell_at:
            # Sell on fifth candle
            requests.append(ExecutionRequest(
                symbol=candle.symbol,
                side=OrderSide.SELL,
                quantity=Decimal("0.1"),
            ))

        return requests


@pytest.mark.asyncio
async def test_runtime_processes_all_candles() -> None:
    """Test that runtime processes all candles from market data."""
    candles = create_test_candles(count=5)
    market_data = PaperMarketData(candles)
    execution_engine = PaperExecutionEngine()
    
    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        checkpoint_interval=1,
    )

    await runtime.run_async()

    assert runtime.candles_processed == 5
    assert execution_engine.last_sequence == 5
    assert execution_engine.last_candle == candles[-1]


@pytest.mark.asyncio
async def test_runtime_restores_state_and_continues() -> None:
    """Test that runtime restores state and continues from checkpoint."""
    repository = InMemoryPaperStateRepository()
    
    # Simulate previous run: processed 3 candles, has a position
    await repository.save_state(PaperRuntimeState(
        last_processed_timestamp=datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc),
        last_market_sequence=3,
        cash_balance=Decimal("9000"),
    ))

    # Create 10 candles total
    all_candles = create_test_candles(count=10)
    
    # Market data starts from beginning (simulating restart)
    market_data = PaperMarketData(all_candles)
    
    # Execution engine will restore state from repository
    execution_engine = PaperExecutionEngine(state_repository=repository)
    
    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        state_repository=repository,
        checkpoint_interval=1,
    )

    # Restore state before running
    restored_state = await runtime.restore_state()
    
    assert restored_state is not None
    assert restored_state.last_market_sequence == 3
    assert execution_engine.last_sequence == 3

    # Run - should skip first 3 candles and process remaining 7
    await runtime.run_async()

    # Should have processed only candles 4-10 (7 candles)
    assert runtime.candles_processed == 7
    assert execution_engine.last_sequence == 10


@pytest.mark.asyncio
async def test_runtime_checkpoints_after_candle() -> None:
    """Test that runtime saves checkpoint after processing candles."""
    repository = InMemoryPaperStateRepository()
    candles = create_test_candles(count=3)
    market_data = PaperMarketData(candles)
    execution_engine = PaperExecutionEngine(state_repository=repository)
    
    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        state_repository=repository,
        checkpoint_interval=1,  # Checkpoint every candle
    )

    await runtime.run_async()

    # Verify state was saved
    saved_state = await repository.load_state()
    assert saved_state is not None
    assert saved_state.last_market_sequence == 3
    assert saved_state.last_processed_timestamp == candles[-1].open_time


@pytest.mark.asyncio
async def test_runtime_skips_already_processed_candles() -> None:
    """Test that runtime skips candles already processed in previous run."""
    repository = InMemoryPaperStateRepository()
    
    # Pre-populate with state showing 5 candles processed
    candles = create_test_candles(count=10)
    initial_candles = candles[:5]
    
    # Process first 5 candles
    market_data_1 = PaperMarketData(initial_candles)
    execution_engine_1 = PaperExecutionEngine(state_repository=repository)
    
    runtime_1 = PaperTradingRuntime(
        market_data=market_data_1,
        execution_engine=execution_engine_1,
        state_repository=repository,
        checkpoint_interval=1,
    )
    
    await runtime_1.run_async()
    
    assert execution_engine_1.last_sequence == 5
    
    # Now restart with all 10 candles
    market_data_2 = PaperMarketData(candles)
    execution_engine_2 = PaperExecutionEngine(state_repository=repository)
    
    runtime_2 = PaperTradingRuntime(
        market_data=market_data_2,
        execution_engine=execution_engine_2,
        state_repository=repository,
        checkpoint_interval=1,
    )
    
    await runtime_2.restore_state()
    await runtime_2.run_async()
    
    # Should only process candles 6-10 (5 new candles)
    assert runtime_2.candles_processed == 5
    assert execution_engine_2.last_sequence == 10


@pytest.mark.asyncio
async def test_runtime_with_strategy_execution() -> None:
    """Test runtime executes strategy orders."""
    repository = InMemoryPaperStateRepository()
    candles = create_test_candles(count=6)
    market_data = PaperMarketData(candles)
    execution_engine = PaperExecutionEngine(
        fill_simulator=FillSimulator(),
        state_repository=repository,
    )
    
    strategy = SimpleTestStrategy(buy_at=1, sell_at=5)
    
    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        strategy=strategy,
        state_repository=repository,
        checkpoint_interval=1,
    )

    await runtime.run_async()

    # Verify orders were executed
    assert len(repository._orders) == 2  # Buy and sell
    assert len(repository._fills) == 2
    
    # Position should be closed after sell
    position = execution_engine.positions.get("BTCUSDT")
    assert position is not None
    assert position.quantity == Decimal("0")


@pytest.mark.asyncio
async def test_runtime_with_risk_manager() -> None:
    """Test runtime validates orders through risk manager."""
    candles = create_test_candles(count=3)
    market_data = PaperMarketData(candles)
    execution_engine = PaperExecutionEngine()
    
    # Risk manager that rejects large orders
    risk_manager = DefaultRiskManager(
        max_position_size=Decimal("0.05"),  # Reject 0.1
        max_order_value=Decimal("100000"),
    )
    
    class LargeOrderStrategy:
        async def on_candle(self, candle, engine):
            from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide
            return [ExecutionRequest(
                symbol=candle.symbol,
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),  # Exceeds max_position_size
            )]
    
    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        strategy=LargeOrderStrategy(),
        risk_manager=risk_manager,
        checkpoint_interval=1,
    )

    await runtime.run_async()

    # No orders should be executed due to risk validation
    assert execution_engine.last_sequence == 3
    assert len(execution_engine.positions) == 0


@pytest.mark.asyncio
async def test_runtime_graceful_shutdown() -> None:
    """Test runtime handles graceful shutdown."""
    candles = create_test_candles(count=10)
    market_data = PaperMarketData(candles)
    execution_engine = PaperExecutionEngine()
    
    runtime = PaperTradingRuntime(
        market_data=market_data,
        execution_engine=execution_engine,
        checkpoint_interval=1,
    )

    # Start runtime in background
    run_task = asyncio.create_task(runtime.run_async())
    
    # Let it process a few candles
    await asyncio.sleep(0.1)
    
    # Request shutdown
    runtime.stop()
    
    # Wait for completion
    try:
        await asyncio.wait_for(run_task, timeout=2.0)
    except asyncio.TimeoutError:
        pass  # May have already completed
    
    # Runtime should be stopped
    assert not runtime.is_running


@pytest.mark.asyncio
async def test_runtime_no_duplicate_candles_after_restart() -> None:
    """Critical test: after restart, no candle is processed twice."""
    repository = InMemoryPaperStateRepository()
    
    # Track which sequences were processed
    processed_sequences = []
    
    class TrackingStrategy:
        async def on_candle(self, candle, engine):
            processed_sequences.append(engine.last_sequence)
            return []
    
    # First run: process 5 candles
    candles_1 = create_test_candles(count=5)
    market_data_1 = PaperMarketData(candles_1)
    execution_engine_1 = PaperExecutionEngine(state_repository=repository)
    
    runtime_1 = PaperTradingRuntime(
        market_data=market_data_1,
        execution_engine=execution_engine_1,
        strategy=TrackingStrategy(),
        state_repository=repository,
        checkpoint_interval=1,
    )
    
    await runtime_1.run_async()
    first_run_sequences = processed_sequences.copy()
    
    # Second run: continue with 10 candles total
    candles_2 = create_test_candles(count=10)
    market_data_2 = PaperMarketData(candles_2)
    execution_engine_2 = PaperExecutionEngine(state_repository=repository)
    
    processed_sequences.clear()
    
    runtime_2 = PaperTradingRuntime(
        market_data=market_data_2,
        execution_engine=execution_engine_2,
        strategy=TrackingStrategy(),
        state_repository=repository,
        checkpoint_interval=1,
    )
    
    await runtime_2.restore_state()
    await runtime_2.run_async()
    
    # Verify no duplicates
    all_sequences = first_run_sequences + processed_sequences
    assert len(all_sequences) == len(set(all_sequences)), "Duplicate sequences detected!"
    
    # First run should have 1-5, second run should have 6-10
    assert first_run_sequences == [1, 2, 3, 4, 5]
    assert processed_sequences == [6, 7, 8, 9, 10]
