"""Public event and result contracts for managed market processing."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.models.market_event import MarketEvent


class PipelineStatus(StrEnum):
    PROCESSED = "PROCESSED"
    IGNORED = "IGNORED"
    WARMUP = "WARMUP"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PipelineResult:
    status: PipelineStatus
    sequence: int
    trading_ready: bool
    signal: Any = None
    risk_decision: Any = None
    execution: Any = None
    reason: str | None = None
    stages: tuple[str, ...] = field(default_factory=tuple)


__all__ = ["MarketEvent", "PipelineResult", "PipelineStatus"]
