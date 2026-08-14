from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.candle import Candle


@dataclass(frozen=True)
class PaperFill:
    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: object


class PaperExecutionEngine:
    """Deterministic execution engine for paper trading.

    Consumes market candles only. It does not communicate with exchanges
    and does not bypass Risk Engine decisions.
    """

    def __init__(self) -> None:
        self._last_candle_time = None
        self._fills: list[PaperFill] = []

    @property
    def fills(self) -> list[PaperFill]:
        return list(self._fills)

    @property
    def last_candle_time(self):
        return self._last_candle_time

    def on_candle(self, candle: Candle) -> None:
        candle.validate()

        if self._last_candle_time is not None:
            if candle.open_time <= self._last_candle_time:
                return

        self._last_candle_time = candle.open_time

    def execute_market_order(self, symbol: str, quantity: Decimal, candle: Candle) -> PaperFill:
        candle.validate()

        fill = PaperFill(
            symbol=symbol,
            price=candle.close,
            quantity=quantity,
            timestamp=candle.close_time,
        )

        self._fills.append(fill)
        return fill
