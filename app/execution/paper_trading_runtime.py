from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

import structlog

from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.exchange.paper_state_repository import PaperStateRepository
from app.models.candle import Candle
from app.models.market_event import MarketEvent
from app.models.paper_state import PaperRuntimeState
from app.monitoring.heartbeat import Heartbeat
from app.monitoring.paper_metrics import PaperMetricsCollector

logger = logging.getLogger(__name__)
event_logger = structlog.get_logger()


class StrategyProtocol(Protocol):
    """Protocol for trading strategies."""

    async def on_candle(self, candle: Candle, engine: PaperExecutionEngine) -> list[ExecutionRequest]:
        """Process candle and return execution requests."""
        ...


class RiskManagerProtocol(Protocol):
    """Protocol for risk management."""

    async def validate_request(self, request: ExecutionRequest, engine: PaperExecutionEngine) -> bool:
        """Validate execution request against risk limits."""
        ...


class PaperTradingRuntime:
    """Main runtime loop for paper trading with recovery support.

    This component orchestrates:
    - Market data streaming from PaperMarketData
    - State restoration from persistence
    - Strategy execution via PaperExecutionEngine
    - Graceful shutdown with checkpointing
    - Metrics emission for monitoring
    """

    def __init__(
        self,
        market_data: Any,
        execution_engine: PaperExecutionEngine,
        strategy: StrategyProtocol | None = None,
        risk_manager: RiskManagerProtocol | None = None,
        state_repository: PaperStateRepository | None = None,
        metrics_collector: PaperMetricsCollector | None = None,
        checkpoint_interval: int = 1,  # Checkpoint every N candles
        heartbeat: Heartbeat | None = None,
    ) -> None:
        self.market_data = market_data
        self.execution_engine = execution_engine
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.state_repository = state_repository
        self.metrics_collector = metrics_collector
        self.checkpoint_interval = checkpoint_interval
        self.heartbeat = heartbeat

        self._running = False
        self._candles_processed = 0
        self._last_checkpoint_sequence = 0
        self._start_time: datetime | None = None
        self._shutdown_event = asyncio.Event()
        self.trading_enabled = True
        self.session_id: str | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def candles_processed(self) -> int:
        return self._candles_processed

    @property
    def last_checkpoint_sequence(self) -> int:
        return self._last_checkpoint_sequence

    @property
    def start_time(self) -> datetime | None:
        return self._start_time

    async def restore_state(self) -> PaperRuntimeState | None:
        """Restore previous runtime state from persistence.

        Returns:
            Restored state or None if no previous state exists.
        """
        if self.state_repository is None:
            logger.info("No state repository configured, starting fresh")
            return None

        try:
            state = await self.state_repository.load_state()
            if state is not None:
                logger.info(
                    "Restored state: sequence=%d, timestamp=%s, cash=%s",
                    state.last_market_sequence,
                    state.last_processed_timestamp,
                    state.cash_balance,
                )
                # Restore execution engine state
                await self.execution_engine.restore_state()
                event_logger.info(
                    "state_restored", sequence=state.last_market_sequence
                )

                # Emit metrics event
                if self.metrics_collector is not None:
                    self.metrics_collector.emit_state_restored(
                        last_sequence=state.last_market_sequence,
                        last_timestamp=state.last_processed_timestamp,
                        cash_balance=state.cash_balance,
                    )

                return state
            else:
                logger.info("No previous state found, starting fresh")
                return None
        except Exception as e:
            logger.error("Failed to restore state: %s", e)
            if self.metrics_collector is not None:
                self.metrics_collector.emit_execution_error(e)
            raise

    async def _checkpoint(self) -> None:
        """Save current state to persistence."""
        if self.state_repository is None:
            return

        try:
            await self.execution_engine.flush()
            await self.execution_engine._save_state()
            self._last_checkpoint_sequence = self.execution_engine.last_sequence
            logger.debug(
                "Checkpoint saved: sequence=%d",
                self._last_checkpoint_sequence,
            )

            # Emit metrics event
            if self.metrics_collector is not None:
                self.metrics_collector.emit_checkpoint_saved(self._last_checkpoint_sequence)
            event_logger.info(
                "checkpoint_saved", sequence=self._last_checkpoint_sequence
            )

        except Exception as e:
            logger.error("Failed to save checkpoint: %s", e)
            if self.metrics_collector is not None:
                self.metrics_collector.emit_execution_error(e)
            raise

    async def _process_candle(self, event: MarketEvent) -> None:
        """Process a single market event (candle).

        Flow:
        1. Update execution engine with market data
        2. Run strategy on_candle
        3. Validate requests through risk manager
        4. Execute validated requests
        5. Checkpoint if interval reached
        """
        candle = event.candle
        sequence = event.sequence

        # Skip already processed candles (recovery scenario)
        if sequence <= self.execution_engine.last_sequence:
            logger.debug("Skipping already processed candle: sequence=%d", sequence)
            event_logger.info("duplicate_event_ignored", sequence=sequence)
            if self.metrics_collector is not None:
                self.metrics_collector.emit_duplicate_event_ignored(sequence)
            return

        logger.debug("Processing candle: sequence=%d, time=%s", sequence, candle.open_time)

        # Update execution engine with market data
        self.execution_engine.on_market_event(event)

        # Run strategy if configured
        source_ready = getattr(self.market_data, "ready", True)
        if self.strategy is not None and self.trading_enabled and source_ready:
            try:
                requests = await self.strategy.on_candle(candle, self.execution_engine)

                for request_index, request in enumerate(requests):
                    # Validate through risk manager
                    if self.risk_manager is not None:
                        if not await self.risk_manager.validate_request(request, self.execution_engine):
                            logger.warning("Risk validation failed for request: %s", request)

                            # Emit metrics event
                            if self.metrics_collector is not None:
                                self.metrics_collector.emit_risk_rejected(
                                    sequence=sequence,
                                    symbol=request.symbol,
                                    reason="Risk limit exceeded",
                                )
                            continue

                    # Execute the request
                    try:
                        result = self.execution_engine.execute(
                            request,
                            client_order_id=(
                                f"{self.session_id or 'paper'}:{sequence}:{request_index}:"
                                f"{request.symbol}:{request.side.value}"
                            ),
                        )
                        logger.info(
                            "Executed: %s %s @ %s (qty=%s)",
                            result.side, result.symbol, result.price, result.quantity,
                        )

                        # Emit metrics event
                        if self.metrics_collector is not None:
                            self.metrics_collector.emit_order_executed(
                                sequence=sequence,
                                symbol=result.symbol,
                                side=result.side.value,
                                quantity=result.quantity,
                                price=result.price,
                            )

                    except Exception as e:
                        logger.error("Execution failed: %s", e)
                        if self.metrics_collector is not None:
                            self.metrics_collector.emit_execution_error(e, sequence=sequence, symbol=request.symbol)
                        raise

            except Exception as e:
                logger.error("Strategy error: %s", e)
                if self.metrics_collector is not None:
                    self.metrics_collector.emit_execution_error(e, sequence=sequence, symbol=candle.symbol)
                raise

        self._candles_processed += 1

        # Emit candle processed metric
        if self.metrics_collector is not None:
            self.metrics_collector.emit_candle_processed(
                sequence=sequence,
                symbol=candle.symbol,
                open_time=candle.open_time,
            )

        # Checkpoint at specified interval
        if self._candles_processed % self.checkpoint_interval == 0:
            await self._checkpoint()
        if self.heartbeat is not None:
            await self.heartbeat.beat(
                state="RUNNING",
                sequence=sequence,
                last_market_event_time=candle.close_time,
            )

    async def run_async(self, *, restore_on_start: bool = True) -> None:
        """Run the paper trading runtime asynchronously.

        This method:
        1. Restores previous state if available
        2. Streams market events
        3. Processes each candle
        4. Handles graceful shutdown
        """
        if self._running:
            raise RuntimeError("Runtime is already running")

        self._running = True
        self._start_time = datetime.now(UTC)
        self._shutdown_event.clear()

        logger.info("PaperTradingRuntime starting...")

        # Emit runtime started metric
        restored = False
        if self.metrics_collector is not None:
            self.metrics_collector.emit_runtime_started(restored_from_checkpoint=False)

        try:
            # Restore state
            restored_state = await self.restore_state() if restore_on_start else None

            if restored_state is not None:
                restored = True
                logger.info(
                    "State restored: last_sequence=%d, last_timestamp=%s",
                    restored_state.last_market_sequence,
                    restored_state.last_processed_timestamp,
                )

                # Update metrics collector with restore status
                if self.metrics_collector is not None:
                    self.metrics_collector.emit_runtime_started(restored_from_checkpoint=True)

            # Process market events
            async for event in self._market_event_stream():
                if self._shutdown_event.is_set():
                    logger.info("Shutdown requested, stopping...")
                    break

                await self._process_candle(event)

        except asyncio.CancelledError:
            logger.info("Runtime cancelled")
            raise
        except Exception as e:
            logger.error("Runtime error: %s", e)
            raise
        finally:
            # Final checkpoint
            await self._checkpoint()
            self._running = False

            # Emit runtime stopped metric
            if self.metrics_collector is not None:
                self.metrics_collector.emit_runtime_stopped(reason="normal shutdown" if not self._shutdown_event.is_set() else "user requested")

            logger.info("PaperTradingRuntime stopped. Candles processed: %d", self._candles_processed)

    async def _market_event_stream(self) -> AsyncIterator[MarketEvent]:
        """Stream market events from PaperMarketData.

        Yields:
            MarketEvent instances from the market data source.
        """
        if hasattr(self.market_data, "stream_async"):
            async for event in self.market_data.stream_async():
                if self._shutdown_event.is_set():
                    break
                yield event
        else:
            for event in self.market_data.stream():
                if self._shutdown_event.is_set():
                    break
                yield event
                await asyncio.sleep(0)

    def stop(self) -> None:
        """Request graceful shutdown."""
        logger.info("Stop requested")
        self._shutdown_event.set()
        stop_source = getattr(self.market_data, "stop", None)
        if stop_source is not None:
            stop_source()

    async def checkpoint(self) -> None:
        """Persist a checkpoint even when the market loop was never started."""
        await self._checkpoint()

    async def shutdown(self) -> None:
        """Gracefully shutdown the runtime."""
        self.stop()

        # Wait for final checkpoint
        while self._running:
            await asyncio.sleep(0.1)

        logger.info("Graceful shutdown complete")


class DefaultRiskManager:
    """Simple risk manager for paper trading."""

    def __init__(
        self,
        max_position_size: Decimal | None = None,
        max_order_value: Decimal | None = None,
    ) -> None:
        self.max_position_size = max_position_size
        self.max_order_value = max_order_value

    async def validate_request(self, request: ExecutionRequest, engine: PaperExecutionEngine) -> bool:
        """Validate execution request."""
        if self.max_order_value is not None:
            price = engine.last_candle.close if engine.last_candle else Decimal("0")
            order_value = request.quantity * price
            if order_value > self.max_order_value:
                return False

        if self.max_position_size is not None:
            current_position = engine.positions.get(request.symbol)
            current_qty = current_position.quantity if current_position else Decimal("0")

            if request.side == OrderSide.BUY:
                new_qty = current_qty + request.quantity
            else:
                new_qty = abs(current_qty - request.quantity)

            if new_qty > self.max_position_size:
                return False

        return True
