from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

import structlog


class RuntimeState(Enum):
    CREATED = "created"
    PREFLIGHT = "preflight"
    RESTORING = "restoring"
    WARMUP = "warmup"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


_NEXT = {
    RuntimeState.CREATED: {RuntimeState.PREFLIGHT, RuntimeState.STOPPING},
    RuntimeState.PREFLIGHT: {RuntimeState.RESTORING, RuntimeState.STOPPING},
    RuntimeState.RESTORING: {RuntimeState.WARMUP, RuntimeState.STOPPING},
    RuntimeState.WARMUP: {RuntimeState.RUNNING, RuntimeState.STOPPING},
    RuntimeState.RUNNING: {RuntimeState.STOPPING},
    RuntimeState.STOPPING: {RuntimeState.STOPPED},
    RuntimeState.STOPPED: set(),
}


class RuntimeLifecycle:
    """Validate and audit every application lifecycle transition."""

    def __init__(self) -> None:
        self.state = RuntimeState.CREATED
        self.history = [self.state]
        self._logger = structlog.get_logger()

    def transition(self, target: RuntimeState) -> None:
        if target not in _NEXT[self.state]:
            raise RuntimeError(f"Invalid runtime transition: {self.state.name} -> {target.name}")
        previous = self.state
        self.state = target
        self.history.append(target)
        self._logger.info(
            "runtime_state_changed",
            **{
                "from": previous.name,
                "to": target.name,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
