"""Fail-closed orchestration from an exchange event to durable paper state."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from app.pipeline.events import MarketEvent, PipelineResult, PipelineStatus
from app.pipeline.pipeline_state import MarketReadiness, PipelineState, PipelineStateTracker


class MarketPipeline:
    """Order the market stages while leaving business logic in injected services.

    Stage dependencies intentionally use small duck-typed boundaries. Production
    adapters and deterministic test doubles can therefore share this orchestrator.
    """

    def __init__(
        self,
        indicator_collector: Any = None,
        *,
        raw_store: Any = None,
        dds_transformer: Any = None,
        indicator_service: Any = None,
        regime_service: Any = None,
        strategy: Any = None,
        risk_engine: Any = None,
        execution_engine: Any = None,
        persistence: Any = None,
        risk_event_store: Any = None,
        mart_refresh: Callable[[], Awaitable[Any]] | None = None,
        required_candles: int = 200,
        symbols: set[str] | None = None,
        state: PipelineStateTracker | None = None,
    ) -> None:
        self.indicator_collector = indicator_collector
        self.raw_store = raw_store
        self.dds_transformer = dds_transformer
        self.indicator_service = indicator_service
        self.regime_service = regime_service
        self.strategy = strategy
        self.risk_engine = risk_engine
        self.execution_engine = execution_engine
        self.persistence = persistence
        self.risk_event_store = risk_event_store
        self.mart_refresh = mart_refresh
        self.symbols = symbols or set()
        self.tracker = state or PipelineStateTracker(
            readiness=MarketReadiness(required_candles=required_candles)
        )
        self._mart_task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._logger = structlog.get_logger()

    async def process_new_candles(self, symbol: str, interval: str) -> int:
        """Compatibility entry point for scheduled incremental indicator loading."""
        if self.indicator_collector is None:
            raise RuntimeError("indicator_collector is not configured")
        return int(
            await self._call(
                self.indicator_collector, "calculate_missing", symbol=symbol, interval=interval
            )
        )

    @property
    def pipeline_state(self) -> PipelineState:
        return self.tracker.state

    def is_trading_ready(self, symbol: str | None = None) -> bool:
        if self.tracker.state is not PipelineState.READY:
            return False
        return self.tracker.readiness.is_ready(symbol) if symbol else True

    def restore_checkpoint(self, last_sequences: dict[str, int]) -> None:
        """Restore sequence guards before consuming any exchange events."""
        self.tracker.last_sequences.update(last_sequences)

    async def process_market_event(self, event: MarketEvent) -> PipelineResult:
        """Process one closed candle atomically from RAW through checkpoint."""
        async with self._lock:
            stages: list[str] = []
            symbol = event.candle.symbol
            if event.sequence <= self.tracker.last_sequence(symbol):
                return PipelineResult(
                    PipelineStatus.IGNORED,
                    event.sequence,
                    self.is_trading_ready(symbol),
                    reason="duplicate sequence",
                    stages=tuple(stages),
                )

            try:
                await self._call(self.raw_store, "save", event)
                stages.append("RAW")
                self._validate_closed_event(event)
                candle = await self._call(self.dds_transformer, "normalize", event)
                candle.validate()
                stages.append("DDS")
                # The paper engine must advance on every accepted candle, not only
                # on candles that produce a signal, so its durable sequence remains
                # the authoritative restart checkpoint.
                await self._call_optional(self.execution_engine, "on_market_event", event)
                indicators = await self._call(self.indicator_service, "calculate", candle)
                stages.append("INDICATORS")
                regime = await self._call(self.regime_service, "detect", candle, indicators)
                stages.append("REGIME")

                self.symbols.add(symbol)
                self.tracker.readiness.observe(symbol, indicators, regime)
                self.tracker.state = (
                    PipelineState.READY
                    if self.tracker.readiness.all_ready(self.symbols)
                    else PipelineState.WARMUP
                )

                signal = risk_decision = execution = None
                if self.is_trading_ready(symbol):
                    signal = await self._call(self.strategy, "evaluate", candle, indicators, regime)
                    stages.append("STRATEGY")
                    if signal is not None:
                        risk_decision = await self._call(self.risk_engine, "evaluate", signal)
                        stages.append("RISK")
                        if self._approved(risk_decision):
                            execution = await self._call(
                                self.execution_engine, "execute", signal, event.sequence
                            )
                            stages.append("EXECUTION")
                        else:
                            await self._risk_event(event, "risk rejected signal", risk_decision)

                await self._call(
                    self.persistence,
                    "persist",
                    event,
                    candle,
                    indicators,
                    regime,
                    signal,
                    risk_decision,
                    execution,
                )
                await self._call(self.persistence, "checkpoint", symbol, event.sequence)
                stages.extend(("PERSISTENCE", "CHECKPOINT"))
                self.tracker.mark_processed(symbol, event.sequence)
                self._schedule_mart()
                status = (
                    PipelineStatus.PROCESSED
                    if self.is_trading_ready(symbol)
                    else PipelineStatus.WARMUP
                )
                return PipelineResult(
                    status,
                    event.sequence,
                    self.is_trading_ready(symbol),
                    signal,
                    risk_decision,
                    execution,
                    stages=tuple(stages),
                )
            except Exception as exc:
                self.tracker.state = PipelineState.DEGRADED
                await self._risk_event(event, f"pipeline failure: {exc}", None)
                await self._best_effort_checkpoint(symbol, event.sequence)
                self._logger.exception(
                    "market_pipeline_failed", symbol=symbol, sequence=event.sequence
                )
                return PipelineResult(
                    PipelineStatus.FAILED,
                    event.sequence,
                    False,
                    reason=str(exc),
                    stages=tuple(stages),
                )

    async def stop(self) -> None:
        if self._mart_task is not None:
            await self._mart_task
        self.tracker.state = PipelineState.STOPPED

    @staticmethod
    def _validate_closed_event(event: MarketEvent) -> None:
        from datetime import UTC, datetime

        candle = event.candle
        if candle.close_time.tzinfo is None or candle.close_time.utcoffset() is None:
            raise ValueError("candle timestamp must be timezone-aware UTC")
        if candle.close_time.utcoffset().total_seconds() != 0:
            raise ValueError("candle timestamp must be UTC")
        if candle.close_time > datetime.now(UTC):
            raise ValueError("open candle is not processable")

    @staticmethod
    def _approved(decision: Any) -> bool:
        return bool(
            decision if isinstance(decision, bool) else getattr(decision, "approved", False)
        )

    @staticmethod
    async def _call(target: Any, method: str, *args: Any, **kwargs: Any) -> Any:
        if target is None:
            raise RuntimeError(f"pipeline dependency for {method} is not configured")
        result = getattr(target, method)(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    @staticmethod
    async def _call_optional(target: Any, method: str, *args: Any) -> Any:
        callback = getattr(target, method, None)
        if callback is None:
            return None
        result = callback(*args)
        return await result if inspect.isawaitable(result) else result

    async def _risk_event(self, event: MarketEvent, reason: str, detail: Any) -> None:
        try:
            await self._call(self.risk_event_store, "record", event, reason, detail)
        except Exception:
            self._logger.exception("risk_event_persistence_failed", sequence=event.sequence)

    async def _best_effort_checkpoint(self, symbol: str, sequence: int) -> None:
        try:
            await self._call(self.persistence, "checkpoint", symbol, sequence)
        except Exception:
            self._logger.exception("pipeline_checkpoint_failed", sequence=sequence)

    def _schedule_mart(self) -> None:
        if self.mart_refresh is None or (self._mart_task and not self._mart_task.done()):
            return
        self._mart_task = asyncio.create_task(self.mart_refresh(), name="market-pipeline-mart")
