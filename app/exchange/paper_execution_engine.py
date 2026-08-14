from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.exchange.fill_simulator import FillSimulator
from app.models.candle import Candle


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
    """Executes approved paper orders without real exchange calls.

    Market data is consumed through Candle events from PaperMarketData.
    """

    def __init__(self, fill_simulator: FillSimulator | None = None) -> None:
        self.fill_simulator = fill_simulator or FillSimulator()
        self._last_candle: Candle | None = None

    @property
    def last_candle(self) -> Candle | None:
        return self._last_candle

    def on_candle(self, candle: Candle) -> None:
        candle.validate()

        if self._last_candle is not None:
            if candle.open_time <= self._last_candle.open_time:
                return

        self._last_candle = candle

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
