from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class PaperPnLSnapshotState:
    """Serializable PnL and equity-curve point for paper reporting recovery."""

    timestamp: datetime
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

    def validate(self) -> None:
        """Reject values that cannot represent a valid equity-curve point."""
        if self.sequence < 0:
            raise ValueError("Snapshot sequence cannot be negative")
        if self.equity < 0:
            raise ValueError("Snapshot equity cannot be negative")
        if self.fees_paid < 0:
            raise ValueError("Snapshot fees cannot be negative")
        if self.drawdown < 0 or self.drawdown_pct < 0:
            raise ValueError("Snapshot drawdown cannot be negative")
