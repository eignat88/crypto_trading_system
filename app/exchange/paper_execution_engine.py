from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from app.exchange.fill_simulator import FillSimulator
from app.exchange.paper_state_repository import PaperStateRepository
from app.models.candle import Candle
from app.models.market_event import MarketEvent
from app.models.paper_fill_state import PaperFillState
from app.models.paper_order_state import PaperOrderState
from app.models.paper_position_state import PaperPositionState
from app.models.paper_state import PaperRuntimeState


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionStatus(str, Enum):
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

        positions = await self.state_repository.load_positions()
        self.positions = {p.symbol: p for p in positions}

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

    def _schedule(self, coroutine: object) -> None:
        try:
            asyncio.get_running_loop().create_task(coroutine)
        except RuntimeError:
            pass

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
        await self.state_repository.save_order(order)
        await self.state_repository.save_fill(fill)
        await self.state_repository.save_position(position)
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

    def execute(self, request: ExecutionRequest, market_price: Decimal | None = None) -> ExecutionResult:
        if market_price is None:
            if self._last_candle is None:
                raise RuntimeError("No market candle available")
            market_price = self._last_candle.close

        fill = self.fill_simulator.execute(quantity=request.quantity, market_price=market_price)

        order_id = str(uuid4())
        fill_id = str(uuid4())
        now = datetime.now(UTC)

        current = self.positions.get(request.symbol)
        old_qty = current.quantity if current else Decimal("0")
        old_price = current.average_price if current else Decimal("0")
        new_qty = old_qty + fill.quantity if request.side == OrderSide.BUY else old_qty - fill.quantity
        new_price = fill.price if old_qty == 0 else ((old_price * old_qty) + (fill.price * fill.quantity)) / (old_qty + fill.quantity)

        position = PaperPositionState(
            symbol=request.symbol,
            quantity=new_qty,
            average_price=new_price,
        )
        self.positions[request.symbol] = position

        if self.state_repository:
            self._schedule(self._persist_execution(
                PaperOrderState(order_id=order_id, symbol=request.symbol, side=request.side, quantity=fill.quantity, status=ExecutionStatus.FILLED, created_at=now),
                PaperFillState(fill_id=fill_id, order_id=order_id, symbol=request.symbol, quantity=fill.quantity, price=fill.price, executed_at=now),
                position,
            ))

        return ExecutionResult(
            status=ExecutionStatus.FILLED,
            symbol=request.symbol,
            side=request.side,
            quantity=fill.quantity,
            price=fill.price,
        )
