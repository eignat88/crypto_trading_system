from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class Candle:
    exchange_name: str
    symbol: str
    interval_code: str
    open_time: datetime
    close_time: Optional[datetime]
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    quote_volume: Optional[Decimal]
    trade_count: Optional[int]


@dataclass
class Instrument:
    symbol: str
    base_currency: str
    quote_currency: str
    is_active: bool


class BaseExchange(ABC):
    """Base interface for exchange clients."""

    @abstractmethod
    async def get_instruments(self) -> list[Instrument]:
        """Get list of available instruments."""
        ...

    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[Candle]:
        """Get historical candles."""
        ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> Decimal:
        """Get current price for a symbol."""
        ...

    @abstractmethod
    async def get_balance(self) -> dict[str, Decimal]:
        """Get account balance."""
        ...

    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """Get open orders."""
        ...

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Place a new order."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an order."""
        ...

    @abstractmethod
    async def get_executions(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
    ) -> list[dict]:
        """Get trade executions."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if exchange API is available."""
        ...
