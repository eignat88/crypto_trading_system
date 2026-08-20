"""Health projection for the managed market pipeline."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class PipelineHealthStatus(StrEnum):
    READY = "READY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class PipelineHealthResult:
    status: PipelineHealthStatus
    trading_enabled: bool
    emergency_stop: bool
    reason: str | None = None


class PipelineHealthMonitor:
    def check(
        self,
        *,
        indicators: dict[str, object] | None = None,
        required_indicators: Iterable[str] = (),
        execution_error: BaseException | None = None,
        pipeline_error: BaseException | None = None,
    ) -> PipelineHealthResult:
        if execution_error is not None:
            return PipelineHealthResult(
                PipelineHealthStatus.FAILED, False, True, str(execution_error)
            )
        if pipeline_error is not None:
            return PipelineHealthResult(
                PipelineHealthStatus.FAILED, False, True, str(pipeline_error)
            )
        values = indicators or {}
        missing = [name for name in required_indicators if values.get(name) is None]
        if missing:
            return PipelineHealthResult(
                PipelineHealthStatus.DEGRADED,
                False,
                False,
                f"Missing indicators: {', '.join(missing)}",
            )
        return PipelineHealthResult(PipelineHealthStatus.READY, True, False)
