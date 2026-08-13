from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4
from typing import Any

from app.exchange.base_exchange import BaseExchange, Instrument, Candle
from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.exchange.paper_state import PaperState


class PaperExchange(BaseExchange):
    """Simulation exchange. Never sends real orders."""

    def __init__(self, state: PaperState | None = None, execution_engine: PaperExecutionEngine | None = None) -> None:
        self.state = state or PaperState(balances={"USDT": Decimal("10000")})
        self.execution_engine = execution_engine or PaperExecutionEngine()

    async def get_instruments(self) -> list[Instrument]:
        return [
            Instrument("BTCUSDT", "BTC", "USDT", True),
            Instrument("ETHUSDT", "ETH", "USDT", True),
        ]

    async def get_candles(self, symbol: str, interval: str, start_time: datetime, end_time: datetime, limit: int = 1000) -> list[Candle]:
        return []

    async def get_current_price(self, symbol: str) -> Decimal:
        raise NotImplementedError("Paper price feed must be provided by market data layer")

    async def get_balance(self) -> dict[str, Decimal]:
        return self.state.balances.copy()

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return list(self.state.orders.values())

    async def place_order(self, symbol: str, side: str, order_type: str, quantity: Decimal, client_order_id: str, price: Decimal | None = None) -> dict[str, Any]:
        order_id = str(uuid4())
        order = {
            "order_id": order_id,
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "status": "NEW",
            "created_at": datetime.now(timezone.utc),
        }
        self.state.orders[order_id] = order
        return order

    async def execute_order(self, order_id: str, market_price: Decimal) -> dict[str, Any]:
        order = self.state.orders[order_id]
        execution = self.execution_engine.execute(
            ExecutionRequest(
                symbol=order["symbol"],
                side=OrderSide(order["side"]),
                quantity=order["quantity"],
            ),
            market_price,
        )
        record = {
            "order_id": order_id,
            "symbol": execution.symbol,
            "side": execution.side.value,
            "quantity": execution.quantity,
            "price": execution.price,
            "status": execution.status.value,
            "executed_at": datetime.now(timezone.utc),
        }
        order["status"] = execution.status.value
        order["price"] = execution.price
        self.state.executions.append(record)
        return record

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        order = self.state.orders[order_id]
        order["status"] = "CANCELED"
        return order

    async def get_executions(self, symbol: str | None = None, start_time: datetime | None = None) -> list[dict[str, Any]]:
        return self.state.executions.copy()

    async def health_check(self) -> bool:
        return True
