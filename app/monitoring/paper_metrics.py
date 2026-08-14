"""Monitoring metrics for paper trading runtime."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any


logger = logging.getLogger(__name__)


class PaperEventType(str, Enum):
    """Types of paper trading events for monitoring."""

    RUNTIME_STARTED = "paper_runtime_started"
    CANDLE_PROCESSED = "paper_candle_processed"
    STATE_RESTORED = "paper_state_restored"
    EXECUTION_ERROR = "paper_execution_error"
    RUNTIME_STOPPED = "paper_runtime_stopped"
    ORDER_EXECUTED = "paper_order_executed"
    CHECKPOINT_SAVED = "paper_checkpoint_saved"
    RISK_REJECTED = "paper_risk_rejected"


@dataclass
class PaperEvent:
    """A monitoring event from paper trading runtime."""

    event_type: PaperEventType
    timestamp: datetime
    sequence: int | None = None
    symbol: str | None = None
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "sequence": self.sequence,
            "symbol": self.symbol,
            "message": self.message,
            "metadata": self.metadata,
        }


class PaperMetricsCollector:
    """Collect and emit monitoring metrics for paper trading.

    This component is responsible for:
    - Emitting lifecycle events (start, stop, restore)
    - Tracking candle processing
    - Recording execution errors
    - Providing metrics for dashboards/alerting
    """

    def __init__(self, emit_callback: callable | None = None) -> None:
        """Initialize the metrics collector.

        Args:
            emit_callback: Optional callback function(event: PaperEvent)
                for emitting events to external monitoring systems.
        """
        self._emit_callback = emit_callback
        self._events: list[PaperEvent] = []
        self._runtime_start_time: datetime | None = None
        self._runtime_stop_time: datetime | None = None
        self._candles_processed_count: int = 0
        self._errors_count: int = 0
        self._orders_executed_count: int = 0
        self._checkpoints_saved_count: int = 0

    @property
    def events(self) -> list[PaperEvent]:
        """Return copy of all recorded events."""
        return self._events.copy()

    @property
    def candles_processed(self) -> int:
        return self._candles_processed_count

    @property
    def errors_count(self) -> int:
        return self._errors_count

    @property
    def orders_executed(self) -> int:
        return self._orders_executed_count

    @property
    def checkpoints_saved(self) -> int:
        return self._checkpoints_saved_count

    @property
    def uptime(self) -> float | None:
        """Calculate runtime uptime in seconds."""
        if self._runtime_start_time is None:
            return None
        
        end_time = self._runtime_stop_time or datetime.now(timezone.utc)
        return (end_time - self._runtime_start_time).total_seconds()

    def _emit(self, event: PaperEvent) -> None:
        """Emit an event to callback and store locally."""
        self._events.append(event)
        
        if self._emit_callback is not None:
            try:
                self._emit_callback(event)
            except Exception as e:
                logger.error("Failed to emit event %s: %s", event.event_type, e)
        
        # Also log at appropriate level
        self._log_event(event)

    def _log_event(self, event: PaperEvent) -> None:
        """Log event to standard logging."""
        level = logging.INFO
        if event.event_type == PaperEventType.EXECUTION_ERROR:
            level = logging.ERROR
        elif event.event_type == PaperEventType.RISK_REJECTED:
            level = logging.WARNING

        logger.log(
            level,
            "[%s] %s - %s",
            event.event_type.value,
            event.timestamp.isoformat(),
            event.message or "",
        )

    def emit_runtime_started(self, restored_from_checkpoint: bool = False) -> None:
        """Emit event when runtime starts.

        Args:
            restored_from_checkpoint: Whether runtime was restored from previous state.
        """
        self._runtime_start_time = datetime.now(timezone.utc)
        
        event = PaperEvent(
            event_type=PaperEventType.RUNTIME_STARTED,
            timestamp=self._runtime_start_time,
            message="Paper trading runtime started",
            metadata={
                "restored_from_checkpoint": restored_from_checkpoint,
            },
        )
        self._emit(event)

    def emit_candle_processed(self, sequence: int, symbol: str, open_time: datetime) -> None:
        """Emit event when a candle is processed.

        Args:
            sequence: Market event sequence number
            symbol: Candle symbol
            open_time: Candle open time
        """
        self._candles_processed_count += 1
        
        event = PaperEvent(
            event_type=PaperEventType.CANDLE_PROCESSED,
            timestamp=datetime.now(timezone.utc),
            sequence=sequence,
            symbol=symbol,
            message=f"Processed candle {sequence} for {symbol}",
            metadata={
                "open_time": open_time.isoformat(),
            },
        )
        self._emit(event)

    def emit_state_restored(
        self,
        last_sequence: int,
        last_timestamp: datetime | None,
        cash_balance: Any,
    ) -> None:
        """Emit event when state is restored from persistence.

        Args:
            last_sequence: Last processed sequence number
            last_timestamp: Timestamp of last processed candle
            cash_balance: Restored cash balance
        """
        event = PaperEvent(
            event_type=PaperEventType.STATE_RESTORED,
            timestamp=datetime.now(timezone.utc),
            sequence=last_sequence,
            message=f"State restored from sequence {last_sequence}",
            metadata={
                "last_sequence": last_sequence,
                "last_timestamp": last_timestamp.isoformat() if last_timestamp else None,
                "cash_balance": str(cash_balance),
            },
        )
        self._emit(event)

    def emit_execution_error(
        self,
        error: Exception,
        sequence: int | None = None,
        symbol: str | None = None,
    ) -> None:
        """Emit event when an execution error occurs.

        Args:
            error: The exception that occurred
            sequence: Sequence number if available
            symbol: Symbol if available
        """
        self._errors_count += 1
        
        event = PaperEvent(
            event_type=PaperEventType.EXECUTION_ERROR,
            timestamp=datetime.now(timezone.utc),
            sequence=sequence,
            symbol=symbol,
            message=f"Execution error: {error}",
            metadata={
                "error_type": type(error).__name__,
                "error_message": str(error),
            },
        )
        self._emit(event)

    def emit_runtime_stopped(self, reason: str | None = None) -> None:
        """Emit event when runtime stops.

        Args:
            reason: Optional reason for stopping
        """
        self._runtime_stop_time = datetime.now(timezone.utc)
        
        event = PaperEvent(
            event_type=PaperEventType.RUNTIME_STOPPED,
            timestamp=self._runtime_stop_time,
            message=f"Paper trading runtime stopped: {reason or 'normal shutdown'}",
            metadata={
                "reason": reason,
                "uptime_seconds": self.uptime,
                "candles_processed": self._candles_processed_count,
            },
        )
        self._emit(event)

    def emit_order_executed(
        self,
        sequence: int,
        symbol: str,
        side: str,
        quantity: Any,
        price: Any,
    ) -> None:
        """Emit event when an order is executed.

        Args:
            sequence: Sequence number
            symbol: Order symbol
            side: BUY or SELL
            quantity: Order quantity
            price: Execution price
        """
        self._orders_executed_count += 1
        
        event = PaperEvent(
            event_type=PaperEventType.ORDER_EXECUTED,
            timestamp=datetime.now(timezone.utc),
            sequence=sequence,
            symbol=symbol,
            message=f"Executed {side} {quantity} {symbol} @ {price}",
            metadata={
                "side": side,
                "quantity": str(quantity),
                "price": str(price),
            },
        )
        self._emit(event)

    def emit_checkpoint_saved(self, sequence: int) -> None:
        """Emit event when a checkpoint is saved.

        Args:
            sequence: Sequence number at checkpoint
        """
        self._checkpoints_saved_count += 1
        
        event = PaperEvent(
            event_type=PaperEventType.CHECKPOINT_SAVED,
            timestamp=datetime.now(timezone.utc),
            sequence=sequence,
            message=f"Checkpoint saved at sequence {sequence}",
            metadata={
                "sequence": sequence,
            },
        )
        self._emit(event)

    def emit_risk_rejected(
        self,
        sequence: int,
        symbol: str,
        reason: str,
    ) -> None:
        """Emit event when risk manager rejects an order.

        Args:
            sequence: Sequence number
            symbol: Order symbol
            reason: Rejection reason
        """
        event = PaperEvent(
            event_type=PaperEventType.RISK_REJECTED,
            timestamp=datetime.now(timezone.utc),
            sequence=sequence,
            symbol=symbol,
            message=f"Order rejected by risk: {reason}",
            metadata={
                "reason": reason,
            },
        )
        self._emit(event)

    def get_summary(self) -> dict[str, Any]:
        """Get summary of all collected metrics.

        Returns:
            Dictionary with summary statistics
        """
        return {
            "runtime_start": self._runtime_start_time.isoformat() if self._runtime_start_time else None,
            "runtime_stop": self._runtime_stop_time.isoformat() if self._runtime_stop_time else None,
            "uptime_seconds": self.uptime,
            "candles_processed": self._candles_processed_count,
            "errors_count": self._errors_count,
            "orders_executed": self._orders_executed_count,
            "checkpoints_saved": self._checkpoints_saved_count,
            "total_events": len(self._events),
        }

    def reset(self) -> None:
        """Reset all collected metrics."""
        self._events.clear()
        self._runtime_start_time = None
        self._runtime_stop_time = None
        self._candles_processed_count = 0
        self._errors_count = 0
        self._orders_executed_count = 0
        self._checkpoints_saved_count = 0


# Default instance for convenience
_default_collector: PaperMetricsCollector | None = None


def get_default_collector() -> PaperMetricsCollector:
    """Get or create default metrics collector."""
    global _default_collector
    if _default_collector is None:
        _default_collector = PaperMetricsCollector()
    return _default_collector


def reset_default_collector() -> None:
    """Reset the default collector."""
    global _default_collector
    _default_collector = None
