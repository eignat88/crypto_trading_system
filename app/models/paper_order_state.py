from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperOrderState:
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    status: str
    created_at: datetime
    client_order_id: str | None = None
    run_id: str | None = None
    signal_id: str | None = None
