from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperFillState:
    fill_id: str
    order_id: str
    symbol: str
    quantity: Decimal
    price: Decimal
    executed_at: datetime
