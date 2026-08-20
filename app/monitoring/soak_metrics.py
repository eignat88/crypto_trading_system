"""In-memory, serializable evidence ledger for paper soak validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.monitoring.heartbeat import RuntimeHealth
from app.monitoring.market_health import MarketHealthResult
from app.monitoring.pipeline_health import PipelineHealthResult


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class RiskSnapshot:
    available_capital: Decimal
    used_capital: Decimal
    positions: int
    drawdown: Decimal
    daily_loss: Decimal
    weekly_loss: Decimal
    risk_state: str
    timestamp: datetime


@dataclass(frozen=True)
class PnlSnapshot:
    initial_capital: Decimal
    equity: Decimal
    cash: Decimal
    unrealized_pnl: Decimal
    realized_pnl: Decimal
    fees: Decimal
    drawdown: Decimal
    timestamp: datetime


@dataclass
class SoakMetrics:
    heartbeats: list[RuntimeHealth] = field(default_factory=list)
    lifecycle: list[dict[str, Any]] = field(default_factory=list)
    market_data_lag: list[dict[str, Any]] = field(default_factory=list)
    pipeline_health: list[dict[str, Any]] = field(default_factory=list)
    risk_snapshots: list[RiskSnapshot] = field(default_factory=list)
    pnl_snapshots: list[PnlSnapshot] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    _runtime_candles_observed: int = field(default=0, repr=False)

    def record_runtime_progress(self, candles_processed: int) -> int:
        """Record only newly processed runtime candles since the prior sample."""
        if candles_processed < 0:
            raise ValueError("candles_processed cannot be negative")
        delta = max(0, candles_processed - self._runtime_candles_observed)
        if delta:
            self.increment("market_events", delta)
            self.increment("pipeline_events", delta)
        self._runtime_candles_observed = candles_processed
        return delta

    def record_heartbeat(self, snapshot: RuntimeHealth) -> None:
        if self.heartbeats and snapshot.sequence < self.heartbeats[-1].sequence:
            self.violations.append("heartbeat sequence moved backwards")
        self.heartbeats.append(snapshot)

    def record_lifecycle(self, state: str, timestamp: datetime) -> None:
        self.lifecycle.append({"state": state.upper(), "timestamp": timestamp})

    def record_market_lag(
        self,
        symbol: str,
        candle_time: datetime,
        expected_time: datetime,
        result: MarketHealthResult,
    ) -> None:
        self.market_data_lag.append(
            {
                "symbol": symbol,
                "last_candle_timestamp": candle_time,
                "expected_timestamp": expected_time,
                "lag_seconds": result.lag_seconds,
                "missed_intervals": result.missing_intervals,
                "status": result.status,
                "trading_enabled": result.trading_enabled,
            }
        )
        if not result.trading_enabled:
            self.violations.append(f"critical market lag: {symbol}")

    def record_pipeline(self, result: PipelineHealthResult, **counts: int) -> None:
        self.pipeline_health.append({"status": result.status, "reason": result.reason})
        for name, amount in counts.items():
            self.increment(name, amount)
        if result.emergency_stop:
            self.violations.append(result.reason or "pipeline failure")

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def to_dict(self) -> dict[str, Any]:
        return {
            "heartbeats": [
                {key: _json_value(value) for key, value in asdict(item).items()}
                | {"uptime_seconds": item.uptime_seconds}
                for item in self.heartbeats
            ],
            "lifecycle": [
                {key: _json_value(value) for key, value in item.items()} for item in self.lifecycle
            ],
            "market_data_lag": [
                {key: _json_value(value) for key, value in item.items()}
                for item in self.market_data_lag
            ],
            "pipeline_health": [
                {key: _json_value(value) for key, value in item.items()}
                for item in self.pipeline_health
            ],
            "risk_snapshots": [
                {key: _json_value(value) for key, value in asdict(item).items()}
                for item in self.risk_snapshots
            ],
            "pnl_snapshots": [
                {key: _json_value(value) for key, value in asdict(item).items()}
                for item in self.pnl_snapshots
            ],
            "counters": dict(self.counters),
            "violations": list(self.violations),
        }
