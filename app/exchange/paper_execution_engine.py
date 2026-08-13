from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.exchange.fill_simulator import FillSimulator


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

    def __init__(self, fill_simulator: FillSimulator | None = None) -> None:
        self.fill_simulator = fill_simulator or FillSimulator()

    def execute(
        self,
        request: ExecutionRequest,
        market_price: Decimal,
    ) -> ExecutionResult:
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
