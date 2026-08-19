"""Rebuild in-memory paper reporting events from durable execution facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from app.reporting.paper_metrics import PaperMetricsCollector


def restore_trade_events(
    collector: PaperMetricsCollector,
    orders: Sequence[Mapping[str, Any]],
    fills: Sequence[Mapping[str, Any]],
) -> None:
    """Restore trades by joining fills to orders using their stable order id.

    Commission is persisted with fills and is therefore trustworthy.  The DDS
    schema does not persist actual slippage, so restored slippage is explicitly
    zero rather than an estimate.
    """
    orders_by_id = {order["order_id"]: order for order in orders}
    seen: set[Any] = set()
    for fill in sorted(fills, key=lambda item: (item["executed_at"], item["fill_id"])):
        fill_id = fill["fill_id"]
        if fill_id in seen:
            continue
        order = orders_by_id.get(fill["order_id"])
        if order is None:
            raise ValueError(f"Order not found for persisted fill {fill_id}")
        collector.record_trade(
            timestamp=fill["executed_at"],
            symbol=fill["symbol"],
            side=order["side"],
            quantity=Decimal(str(fill["quantity"])),
            price=Decimal(str(fill["price"])),
            fee=Decimal(str(fill.get("commission") or 0)),
            slippage=Decimal("0"),
            update_tracker=False,
        )
        seen.add(fill_id)
