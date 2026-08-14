from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PaperPositionState:
    symbol: str
    quantity: Decimal
    average_price: Decimal
