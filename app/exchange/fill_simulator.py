from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class FillResult:
    quantity: Decimal
    price: Decimal
    executed_at: datetime


class FillSimulator:
    """Initial paper fill simulator."""

    def execute(
        self,
        quantity: Decimal,
        market_price: Decimal,
    ) -> FillResult:
        if quantity <= Decimal("0"):
            raise ValueError("quantity must be positive")

        if market_price <= Decimal("0"):
            raise ValueError("market_price must be positive")

        return FillResult(
            quantity=quantity,
            price=market_price,
            executed_at=datetime.now(timezone.utc),
        )
