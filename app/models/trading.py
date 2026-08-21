"""Domain models for the spot-only trading pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4


class SignalAction(StrEnum):
    """Actions supported by the spot MVP."""

    BUY = "buy"
    SELL = "sell"
    OPEN_LONG = "open_long"
    CLOSE = "close"


@dataclass(frozen=True)
class Signal:
    """A strategy intent. It cannot execute an order by itself."""

    action: SignalAction | str
    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    reason: str = ""
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    strategy: str = ""
    parameters_version: str = ""
    indicators: dict[str, Any] = field(default_factory=dict)
    regime: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    signal_id: str = field(default_factory=lambda: str(uuid4()))
    run_id: str = ""


@dataclass(frozen=True)
class Order:
    """A normalized spot order produced from an approved signal."""

    order_id: str
    signal: Signal
    side: str
    quantity: Decimal
    requested_price: Decimal
    created_at: datetime
    run_id: str = ""
    signal_id: str = ""

    @property
    def symbol(self) -> str:
        return self.signal.symbol


@dataclass(frozen=True)
class RiskDecision:
    """Auditable Risk Engine decision for an normalized order."""

    order_id: str
    approved: bool
    risk_level: str
    codes: tuple[str, ...]
    reasons: tuple[str, ...]
    requested_quantity: Decimal
    approved_quantity: Decimal | None = None
    run_id: str = ""
    signal_id: str = ""


@dataclass(frozen=True)
class Fill:
    """Simulated execution result used by the backtest portfolio."""

    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    timestamp: datetime
    run_id: str = ""
    signal_id: str = ""


@dataclass
class Position:
    """A long-only spot position."""

    symbol: str
    side: str
    entry_price: Decimal
    quantity: Decimal
    entry_time: datetime
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    trailing_stop: Decimal | None = None
    unrealized_pnl: Decimal = Decimal("0")
    current_price: Decimal | None = None
    entry_commission: Decimal = Decimal("0")
    high_water_mark: Decimal | None = None
    holding_periods: int = 0

    @property
    def position_value(self) -> Decimal:
        return (self.current_price or self.entry_price) * self.quantity

    def update_market(self, current_price: Decimal, high_price: Decimal | None = None) -> None:
        self.current_price = current_price
        self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        observed_high = high_price or current_price
        self.high_water_mark = max(self.high_water_mark or observed_high, observed_high)
        self.holding_periods += 1
