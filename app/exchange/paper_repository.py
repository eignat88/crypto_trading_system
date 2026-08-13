from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid4

from app.exchange.paper_state import PaperState


class PaperStateSerializer:
    """Serialize paper state for persistence and recovery."""

    @staticmethod
    def dumps(state: PaperState) -> str:
        payload = asdict(state)
        return json.dumps(payload, default=str)

    @staticmethod
    def loads(payload: str) -> PaperState:
        data = json.loads(payload)
        return PaperState(
            balances=data.get("balances", {}),
            orders=data.get("orders", {}),
            executions=data.get("executions", []),
            positions=data.get("positions", {}),
        )


class PaperCheckpoint:
    def __init__(self, state: PaperState) -> None:
        self.id = str(uuid4())
        self.state = state
        self.created_at = datetime.now(timezone.utc)

    def to_json(self) -> str:
        return PaperStateSerializer.dumps(self.state)
