"""State and readiness tracking for the managed market pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PipelineState(StrEnum):
    STARTING = "STARTING"
    WARMUP = "WARMUP"
    READY = "READY"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


@dataclass
class MarketReadiness:
    """Recoverable, per-symbol readiness facts (not trading policy)."""

    required_candles: int = 200
    candle_counts: dict[str, int] = field(default_factory=dict)
    indicators: dict[str, frozenset[str]] = field(default_factory=dict)
    regimes: set[str] = field(default_factory=set)

    def observe(self, symbol: str, indicators: Any, regime: Any) -> None:
        self.candle_counts[symbol] = self.candle_counts.get(symbol, 0) + 1
        names = indicators.keys() if hasattr(indicators, "keys") else ()
        self.indicators[symbol] = frozenset(str(name).upper() for name in names)
        if regime is not None:
            self.regimes.add(symbol)

    def seed(self, symbol: str, candle_count: int) -> None:
        """Seed restored/history candle count without manufacturing derived facts."""
        self.candle_counts[symbol] = max(candle_count, self.candle_counts.get(symbol, 0))

    def is_ready(self, symbol: str) -> bool:
        required = {"EMA", "RSI", "ATR"}
        return (
            self.candle_counts.get(symbol, 0) >= self.required_candles
            and required <= self.indicators.get(symbol, frozenset())
            and symbol in self.regimes
        )

    def all_ready(self, symbols: set[str]) -> bool:
        return bool(symbols) and all(self.is_ready(symbol) for symbol in symbols)


@dataclass
class PipelineStateTracker:
    state: PipelineState = PipelineState.STARTING
    readiness: MarketReadiness = field(default_factory=MarketReadiness)
    last_sequences: dict[str, int] = field(default_factory=dict)

    def last_sequence(self, symbol: str) -> int:
        return self.last_sequences.get(symbol, 0)

    def mark_processed(self, symbol: str, sequence: int) -> None:
        self.last_sequences[symbol] = sequence
