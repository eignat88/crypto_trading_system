from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperPnLSnapshotState:
    """Durable representation of one paper-reporting checkpoint."""

    snapshot_time: datetime
    sequence: int
    equity: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    fees_paid: Decimal
    slippage: Decimal
    cash_balance: Decimal
    position_value: Decimal
    drawdown: Decimal
    drawdown_pct: Decimal
