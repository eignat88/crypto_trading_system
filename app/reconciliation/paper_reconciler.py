"""Periodic paper-state reconciliation between runtime and database.

Compares the live in-memory trading state (orders, fills, positions,
balance) against the persisted PostgreSQL state and classifies every
discrepancy as RECOVERABLE or FATAL.  Fatal discrepancies block new
trading via the Risk Engine; recoverable ones are logged and counted.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

import structlog

logger = structlog.get_logger()


def _extract_quantity(obj: Any) -> Decimal | None:
    """Extract quantity from a position object (dataclass or dict)."""
    if isinstance(obj, dict):
        val = obj.get("quantity")
    else:
        val = getattr(obj, "quantity", None)
    return Decimal(str(val)) if val is not None else None


class DiscrepancySeverity(StrEnum):
    RECOVERABLE = "RECOVERABLE"
    FATAL = "FATAL"


@dataclass(frozen=True)
class Discrepancy:
    category: str
    severity: DiscrepancySeverity
    message: str
    runtime_value: Any = None
    db_value: Any = None


@dataclass
class ReconciliationResult:
    checked_at: datetime
    discrepancies: list[Discrepancy] = field(default_factory=list)
    orders_runtime: int = 0
    orders_db: int = 0
    fills_runtime: int = 0
    fills_db: int = 0
    balance_runtime: Decimal = Decimal("0")
    balance_db: Decimal = Decimal("0")
    position_symbols_runtime: int = 0
    position_symbols_db: int = 0
    success: bool = True

    @property
    def has_fatal(self) -> bool:
        return any(d.severity == DiscrepancySeverity.FATAL for d in self.discrepancies)

    @property
    def fatal_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.FATAL)

    @property
    def recoverable_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.RECOVERABLE)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "success": self.success,
            "has_fatal": self.has_fatal,
            "fatal_count": self.fatal_count,
            "recoverable_count": self.recoverable_count,
            "orders": {"runtime": self.orders_runtime, "db": self.orders_db},
            "fills": {"runtime": self.fills_runtime, "db": self.fills_db},
            "balance": {"runtime": str(self.balance_runtime), "db": str(self.balance_db)},
            "positions": {
                "runtime": self.position_symbols_runtime,
                "db": self.position_symbols_db,
            },
            "discrepancies": [
                {
                    "category": d.category,
                    "severity": d.severity.value,
                    "message": d.message,
                    "runtime_value": str(d.runtime_value) if d.runtime_value is not None else None,
                    "db_value": str(d.db_value) if d.db_value is not None else None,
                }
                for d in self.discrepancies
            ],
        }


class StateReader(Protocol):
    """Reads live runtime state (in-memory)."""

    @property
    def cash_balance(self) -> Decimal: ...
    @property
    def orders(self) -> dict[str, Any]: ...
    @property
    def fills(self) -> dict[str, Any]: ...
    @property
    def positions(self) -> dict[str, Any]: ...


class DatabaseReader(Protocol):
    """Reads persisted state from PostgreSQL."""

    async def load_orders(self) -> list[dict[str, Any]]: ...
    async def load_fills(self) -> list[dict[str, Any]]: ...
    async def load_positions(self) -> list[Any]: ...
    async def load_state(self) -> Any: ...


class PaperReconciler:
    """Compare runtime state against database state and classify discrepancies.

    Discrepancy classification:
    - RECOVERABLE: order/fill count mismatch (may be pending writes),
      position quantity drift within tolerance, balance drift within tolerance.
    - FATAL: missing orders in DB, position exists in DB but not in runtime
      (or vice versa), balance mismatch beyond tolerance.
    """

    def __init__(
        self,
        *,
        balance_tolerance: Decimal = Decimal("0.01"),
        position_tolerance: Decimal = Decimal("0.00000001"),
        state_reader: StateReader | None = None,
        db_reader: DatabaseReader | None = None,
        on_reconciled: Callable[[ReconciliationResult], object] | None = None,
    ) -> None:
        self.balance_tolerance = balance_tolerance
        self.position_tolerance = position_tolerance
        self.state_reader = state_reader
        self.db_reader = db_reader
        self._on_reconciled = on_reconciled
        self._last_result: ReconciliationResult | None = None
        self._consecutive_fatal: int = 0
        self._total_checks: int = 0

    @property
    def last_result(self) -> ReconciliationResult | None:
        return self._last_result

    @property
    def consecutive_fatal(self) -> int:
        return self._consecutive_fatal

    async def reconcile(self) -> ReconciliationResult:
        """Run one reconciliation cycle."""
        self._total_checks += 1
        now = datetime.now(UTC)

        if self.state_reader is None or self.db_reader is None:
            result = ReconciliationResult(checked_at=now, success=False)
            self._last_result = result
            return result

        discrepancies: list[Discrepancy] = []

        # Load state from both sources
        runtime_orders = self.state_reader.orders
        runtime_fills = self.state_reader.fills
        runtime_positions = self.state_reader.positions
        runtime_balance = self.state_reader.cash_balance

        db_orders_list = await self.db_reader.load_orders()
        db_fills_list = await self.db_reader.load_fills()
        db_positions_list = await self.db_reader.load_positions()
        db_state = await self.db_reader.load_state()

        db_orders = {o.get("order_id", o.order_id if hasattr(o, "order_id") else ""): o
                     for o in db_orders_list}
        db_fills = {f.get("fill_id", f.fill_id if hasattr(f, "fill_id") else ""): f
                    for f in db_fills_list}
        db_positions = {p.symbol if hasattr(p, "symbol") else p.get("symbol", ""): p
                        for p in db_positions_list}
        db_balance = Decimal(str(db_state.cash_balance)) if db_state is not None else Decimal("0")

        result = ReconciliationResult(
            checked_at=now,
            orders_runtime=len(runtime_orders),
            orders_db=len(db_orders),
            fills_runtime=len(runtime_fills),
            fills_db=len(db_fills),
            balance_runtime=runtime_balance,
            balance_db=db_balance,
            position_symbols_runtime=len(runtime_positions),
            position_symbols_db=len(db_positions),
        )

        # --- Order checks ---
        runtime_order_ids = set(runtime_orders.keys())
        db_order_ids = set(db_orders.keys())

        missing_in_db = runtime_order_ids - db_order_ids
        for oid in missing_in_db:
            order = runtime_orders[oid]
            status = getattr(order, "status", None)
            # Orders that are not yet flushed to DB are recoverable
            discrepancies.append(Discrepancy(
                category="order_missing_in_db",
                severity=DiscrepancySeverity.RECOVERABLE,
                message=f"Order {oid} exists in runtime but not in database",
                runtime_value=status,
                db_value=None,
            ))

        extra_in_db = db_order_ids - runtime_order_ids
        for oid in extra_in_db:
            discrepancies.append(Discrepancy(
                category="order_missing_in_runtime",
                severity=DiscrepancySeverity.FATAL,
                message=f"Order {oid} exists in database but not in runtime",
                runtime_value=None,
                db_value=db_orders[oid].get("status") if isinstance(db_orders[oid], dict) else "unknown",
            ))

        # --- Fill checks ---
        runtime_fill_ids = set(runtime_fills.keys())
        db_fill_ids = set(db_fills.keys())

        missing_fills = runtime_fill_ids - db_fill_ids
        for fid in missing_fills:
            discrepancies.append(Discrepancy(
                category="fill_missing_in_db",
                severity=DiscrepancySeverity.RECOVERABLE,
                message=f"Fill {fid} exists in runtime but not in database",
            ))

        extra_fills = db_fill_ids - runtime_fill_ids
        for fid in extra_fills:
            discrepancies.append(Discrepancy(
                category="fill_missing_in_runtime",
                severity=DiscrepancySeverity.FATAL,
                message=f"Fill {fid} exists in database but not in runtime",
            ))

        # --- Position checks ---
        runtime_symbols = set(runtime_positions.keys())
        db_symbols = set(db_positions.keys())

        missing_positions = runtime_symbols - db_symbols
        for sym in missing_positions:
            pos = runtime_positions[sym]
            qty = _extract_quantity(pos)
            if qty is not None and qty > self.position_tolerance:
                discrepancies.append(Discrepancy(
                    category="position_missing_in_db",
                    severity=DiscrepancySeverity.FATAL,
                    message=f"Position {sym} exists in runtime but not in database",
                    runtime_value=qty,
                ))

        extra_positions = db_symbols - runtime_symbols
        for sym in extra_positions:
            pos = db_positions[sym]
            qty = _extract_quantity(pos)
            if qty is not None and qty > self.position_tolerance:
                discrepancies.append(Discrepancy(
                    category="position_missing_in_runtime",
                    severity=DiscrepancySeverity.FATAL,
                    message=f"Position {sym} exists in database but not in runtime",
                    db_value=qty,
                ))

        # Position quantity comparison for matching symbols
        for sym in runtime_symbols & db_symbols:
            rt_pos = runtime_positions[sym]
            db_pos = db_positions[sym]
            rt_qty = _extract_quantity(rt_pos) or Decimal("0")
            db_qty = _extract_quantity(db_pos) or Decimal("0")
            if abs(rt_qty - db_qty) > self.position_tolerance:
                discrepancies.append(Discrepancy(
                    category="position_quantity_mismatch",
                    severity=DiscrepancySeverity.FATAL,
                    message=f"Position {sym} quantity mismatch",
                    runtime_value=rt_qty,
                    db_value=db_qty,
                ))

        # --- Balance check ---
        balance_diff = abs(runtime_balance - db_balance)
        if balance_diff > self.balance_tolerance:
            discrepancies.append(Discrepancy(
                category="balance_mismatch",
                severity=DiscrepancySeverity.FATAL,
                message=f"Balance mismatch: runtime={runtime_balance} db={db_balance}",
                runtime_value=runtime_balance,
                db_value=db_balance,
            ))

        result.discrepancies = discrepancies
        result.success = True

        # Track fatal streak
        if result.has_fatal:
            self._consecutive_fatal += 1
        else:
            self._consecutive_fatal = 0

        self._last_result = result

        # Callback
        if self._on_reconciled is not None:
            cb_result = self._on_reconciled(result)
            if inspect.isawaitable(cb_result):
                await cb_result

        # Log
        if result.has_fatal:
            logger.warning(
                "reconciliation_completed_with_fatal",
                fatal_count=result.fatal_count,
                recoverable_count=result.recoverable_count,
            )
        else:
            logger.debug(
                "reconciliation_completed",
                recoverable_count=result.recoverable_count,
            )

        return result
