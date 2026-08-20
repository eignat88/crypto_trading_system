"""State and evidence collected during a paper-trading soak session."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class SoakStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


@dataclass
class SoakSession:
    runtime_id: str
    symbols: tuple[str, ...]
    session_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    status: SoakStatus = SoakStatus.RUNNING
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        self.symbols = tuple(symbol.upper() for symbol in self.symbols)
        if not self.symbols:
            raise ValueError("a soak session requires at least one symbol")
        if self.started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")

    @property
    def duration(self) -> float:
        """Elapsed session duration in seconds."""
        end = self.finished_at or datetime.now(UTC)
        return max(0.0, (end - self.started_at).total_seconds())

    def finish(
        self,
        status: SoakStatus = SoakStatus.COMPLETED,
        reason: str | None = None,
        *,
        at: datetime | None = None,
    ) -> None:
        if self.status is not SoakStatus.RUNNING:
            raise RuntimeError("soak session is already finished")
        if status is SoakStatus.RUNNING:
            raise ValueError("a finished session cannot remain RUNNING")
        if status is SoakStatus.FAILED and not reason:
            raise ValueError("a failed session requires a failure reason")
        self.finished_at = at or datetime.now(UTC)
        if self.finished_at.tzinfo is None:
            raise ValueError("finished_at must be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        self.status = status
        self.failure_reason = reason

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["started_at"] = self.started_at.isoformat()
        value["finished_at"] = self.finished_at.isoformat() if self.finished_at else None
        value["duration"] = self.duration
        value["symbols"] = list(self.symbols)
        value["status"] = self.status.value
        return value
