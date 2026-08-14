from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
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
        self.created_at = datetime.now(UTC)

    def to_json(self) -> str:
        return PaperStateSerializer.dumps(self.state)


class PaperRepository:
    """Persistence boundary for paper trading runtime entities."""

    def __init__(self) -> None:
        self.orders: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []

    async def save_order(self, order: dict[str, Any]) -> None:
        self.orders.append(order.copy())

    async def update_order(self, order: dict[str, Any]) -> None:
        for index, existing in enumerate(self.orders):
            if existing.get("order_id") == order.get("order_id"):
                self.orders[index] = order.copy()
                return

        self.orders.append(order.copy())

    async def save_fill(self, fill: dict[str, Any]) -> None:
        self.fills.append(fill.copy())
