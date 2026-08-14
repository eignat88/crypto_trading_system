from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.exchange.fill_simulator import FillSimulator
from app.exchange.paper_state_repository import PaperStateRepository
from app.models.candle import Candle
from app.models.market_event import MarketEvent
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
    """Executes approved paper orders without real exchange calls."""

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

        if state is None:
            return

        self._last_sequence = state.last_market_sequence
        self.cash_balance = state.cash_balance

    async def _save_state(self) -> None:
        if self.state_repository is None:
            return

        await self.state_repository.save_state(
            PaperRuntimeState(
                last_processed_timestamp=(
                    self._last_candle.open_time if self._last_candle else None
                ),
                last_market_sequence=self._last_sequence,
                cash_balance=self.cash_balance,
            )
        )

    async def on_market_event(self, event: MarketEvent) -> None:
        event.candle.validate()

        if event.sequence <= self._last_sequence:
            return

        if self._last_candle is not None:
            if event.candle.open_time <= self._last_candle.open_time:
                return

        self._last_sequence = event.sequence
        self._last_candle = event.candle

        await self._save_state()

    async def on_candle(self, candle: Candle) -> None:
        await self.on_market_event(
            MarketEvent(candle=candle, sequence=self._last_sequence + 1)
        )

    def execute(
        self,
        request: ExecutionRequest,
        market_price: Decimal | None = None,
    ) -> ExecutionResult:
        if market_price is None:
            if self._last_candle is None:
                raise RuntimeError("No market candle available")
            market_price = self._last_candle.close

        fill = self.fill_simulator.execute(
            quantity=request.quantity,
            market_price=market_price,
        )

        return ExecutionResult(
            status=ExecutionStatus.FILLED,
            symbol=request.symbol,
            side=request.side,
            quantity=fill.quantity,
            price=fill.price,
        )
