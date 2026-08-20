from __future__ import annotations

from copy import deepcopy

from app.models.paper_fill_state import PaperFillState
from app.models.paper_order_state import PaperOrderState
from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState


class MemoryCheckpointRepository:
    """Durable-in-memory boundary shared by separately constructed runtimes."""

    def __init__(self) -> None:
        self.state: PaperRuntimeState | None = None
        self.positions: dict[str, PaperPositionState] = {}
        self.orders: dict[str, PaperOrderState] = {}
        self.fills: dict[str, PaperFillState] = {}
        self.pnl: dict[tuple[object, int], PaperPnLSnapshotState] = {}
        self.checkpoints = 0

    async def save_state(self, state: PaperRuntimeState) -> None:
        self.state = deepcopy(state)
        self.checkpoints += 1

    async def load_state(self) -> PaperRuntimeState | None:
        return deepcopy(self.state)

    async def save_position(self, value: PaperPositionState) -> None:
        self.positions[value.symbol] = deepcopy(value)

    async def load_positions(self) -> list[PaperPositionState]:
        return deepcopy(list(self.positions.values()))

    async def save_order(self, value: PaperOrderState) -> None:
        key = value.client_order_id
        if key is not None:
            duplicate = next(
                (order for order in self.orders.values() if order.client_order_id == key), None
            )
            if duplicate is not None and duplicate.order_id != value.order_id:
                raise RuntimeError("duplicate client order id")
        self.orders[value.order_id] = deepcopy(value)

    async def load_orders(self) -> list[PaperOrderState]:
        return deepcopy(list(self.orders.values()))

    async def save_fill(self, value: PaperFillState) -> None:
        self.fills.setdefault(value.fill_id, deepcopy(value))

    async def load_fills(self) -> list[PaperFillState]:
        return deepcopy(list(self.fills.values()))

    async def save_pnl_snapshot(self, value: PaperPnLSnapshotState) -> None:
        self.pnl[(value.timestamp, value.sequence)] = deepcopy(value)

    async def load_pnl_snapshots(self) -> list[PaperPnLSnapshotState]:
        return deepcopy(list(self.pnl.values()))


class MemoryRiskStore:
    def __init__(self) -> None:
        self.state: dict[str, object] | None = None
        self.events: list[dict[str, object]] = []

    def load_state(self) -> dict[str, object] | None:
        return deepcopy(self.state)

    def save_state(self, state: dict[str, object]) -> None:
        self.state = deepcopy(state)

    def save_event(self, event: dict[str, object]) -> None:
        self.events.append(deepcopy(event))
