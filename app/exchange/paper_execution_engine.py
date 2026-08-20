from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

import structlog

from app.exchange.fill_simulator import FillSimulator
from app.exchange.paper_state_repository import PaperStateRepository
from app.models.candle import Candle
from app.models.market_event import MarketEvent
from app.models.paper_fill_state import PaperFillState
from app.models.paper_order_state import PaperOrderState
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionStatus(StrEnum):
    FILLED = "FILLED"


@dataclass(frozen=True)
class ExecutionRequest:
    symbol: str
    side: OrderSide
    quantity: Decimal


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal


class PaperExecutionEngine:
    """Executes paper orders and persists recoverable trading state."""

    def __init__(
        self,
        fill_simulator: FillSimulator | None = None,
        state_repository: PaperStateRepository | None = None,
    ) -> None:
        self.fill_simulator = fill_simulator or FillSimulator()
        self.state_repository = state_repository
        self._last_candle: Candle | None = None
        self._last_sequence: int = 0
        self.cash_balance = Decimal("0")
        self.positions: dict[str, PaperPositionState] = {}
        self.orders: dict[str, PaperOrderState] = {}
        self.fills: dict[str, PaperFillState] = {}
        self._client_orders: dict[str, str] = {}
        self._pending_writes: set[asyncio.Task[object]] = set()
        self._logger = structlog.get_logger()

    @property
    def last_candle(self) -> Candle | None:
        return self._last_candle

    @property
    def last_sequence(self) -> int:
        return self._last_sequence

    async def restore_state(self) -> None:
        if self.state_repository is None:
            return

        state = await self.state_repository.load_state()
        if state is not None:
            self._last_sequence = state.last_market_sequence
            self.cash_balance = state.cash_balance

        positions = await self.state_repository.load_positions()  # type: ignore[attr-defined]
        self.positions = {p.symbol: p for p in positions}
        load_orders = getattr(self.state_repository, "load_orders", None)
        load_fills = getattr(self.state_repository, "load_fills", None)
        orders = await load_orders() if load_orders else []
        fills = await load_fills() if load_fills else []
        self.orders = {order.order_id: order for order in orders}
        self.fills = {fill.fill_id: fill for fill in fills}
        self._client_orders = {
            order.client_order_id: order.order_id
            for order in orders
            if order.client_order_id is not None
        }
        unknown_orders = {fill.order_id for fill in fills} - self.orders.keys()
        if unknown_orders:
            raise RuntimeError(
                "Paper state restore is incomplete: fills reference missing orders "
                + ", ".join(sorted(unknown_orders))
            )

    async def _save_state(self) -> None:
        if self.state_repository is None:
            return

        await self.state_repository.save_state(
            PaperRuntimeState(
                last_processed_timestamp=self._last_candle.open_time if self._last_candle else None,
                last_market_sequence=self._last_sequence,
                cash_balance=self.cash_balance,
            )
        )

    def _schedule(self, coroutine: Coroutine[Any, Any, object]) -> None:
        try:
            task: asyncio.Task[object] = asyncio.get_running_loop().create_task(coroutine)
            self._pending_writes.add(task)
            task.add_done_callback(self._pending_writes.discard)
        except RuntimeError:
            pass

    async def flush(self) -> None:
        """Wait for every scheduled persistence write before checkpoint/shutdown."""
        if self._pending_writes:
            await asyncio.gather(*tuple(self._pending_writes))

    def _schedule_save_state(self) -> None:
        if self.state_repository:
            self._schedule(self._save_state())

    async def _persist_execution(
        self,
        order: PaperOrderState,
        fill: PaperFillState,
        position: PaperPositionState,
    ) -> None:
        if self.state_repository is None:
            return
        await self.state_repository.save_order(order)  # type: ignore[attr-defined]
        await self.state_repository.save_fill(fill)  # type: ignore[attr-defined]
        await self.state_repository.save_position(position)  # type: ignore[attr-defined]
        await self._save_state()

    def on_market_event(self, event: MarketEvent) -> None:
        event.candle.validate()
        if event.sequence <= self._last_sequence:
            return
        if self._last_candle and event.candle.open_time <= self._last_candle.open_time:
            return
        self._last_sequence = event.sequence
        self._last_candle = event.candle
        self._schedule_save_state()

    def on_candle(self, candle: Candle) -> None:
        self.on_market_event(MarketEvent(candle=candle, sequence=self._last_sequence + 1))

    def execute(
        self,
        request: ExecutionRequest,
        market_price: Decimal | None = None,
        *,
        client_order_id: str | None = None,
    ) -> ExecutionResult:
        if client_order_id is not None and client_order_id in self._client_orders:
            order_id = self._client_orders[client_order_id]
            order = self.orders[order_id]
            restored_fill = next(
                (item for item in self.fills.values() if item.order_id == order_id), None
            )
            self._logger.info("duplicate_order_prevented", client_order_id=client_order_id)
            if restored_fill is None:
                raise RuntimeError(f"Existing order {order_id} has unknown fill state")
            return ExecutionResult(
                status=ExecutionStatus.FILLED,
                symbol=order.symbol,
                side=OrderSide(order.side),
                quantity=restored_fill.quantity,
                price=restored_fill.price,
            )
        if market_price is None:
            if self._last_candle is None:
                raise RuntimeError("No market candle available")
            market_price = self._last_candle.close

        current = self.positions.get(request.symbol)
        old_qty = current.quantity if current else Decimal("0")
        old_price = current.average_price if current else Decimal("0")
        if request.side == OrderSide.SELL and request.quantity > old_qty:
            raise ValueError(
                f"Sell quantity {request.quantity} exceeds position {old_qty} "
                f"for {request.symbol}"
            )

        fill = self.fill_simulator.execute(quantity=request.quantity, market_price=market_price)

        order_id = client_order_id or str(uuid4())
        fill_id = str(uuid4())
        now = datetime.now(UTC)

        current = self.positions.get(request.symbol)
        old_qty = current.quantity if current else Decimal("0")
        old_price = current.average_price if current else Decimal("0")
        if request.side == OrderSide.SELL:
            if fill.quantity > old_qty:
                raise ValueError(
                    f"Sell quantity {fill.quantity} exceeds position {old_qty} "
                    f"for {request.symbol}"
                )
            new_qty = old_qty - fill.quantity
            new_price = old_price if new_qty > 0 else Decimal("0")
        else:
            new_qty = old_qty + fill.quantity
            new_price = (
                fill.price
                if old_qty == 0
                else ((old_price * old_qty) + (fill.price * fill.quantity)) / new_qty
            )

        position = PaperPositionState(
            symbol=request.symbol,
            quantity=new_qty,
            average_price=new_price,
        )
        self.positions[request.symbol] = position

        order = PaperOrderState(
            order_id=order_id, symbol=request.symbol, side=request.side,
            quantity=fill.quantity, status=ExecutionStatus.FILLED, created_at=now,
            client_order_id=client_order_id,
        )
        fill_state = PaperFillState(
            fill_id=fill_id, order_id=order_id, symbol=request.symbol,
            quantity=fill.quantity, price=fill.price, executed_at=now,
        )
        self.orders[order_id] = order
        self.fills[fill_id] = fill_state
        if client_order_id is not None:
            self._client_orders[client_order_id] = order_id

        if self.state_repository:
            self._schedule(self._persist_execution(
                order,
                fill_state,
                position,
            ))

        return ExecutionResult(
            status=ExecutionStatus.FILLED,
            symbol=request.symbol,
            side=request.side,
            quantity=fill.quantity,
            price=fill.price,
        )
