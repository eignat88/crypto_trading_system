from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState


class PostgresPaperRepository:
    """
    PostgreSQL persistence adapter for Paper Trading runtime.

    Responsibility:
    - persist paper orders;
    - persist paper fills;
    - restore paper runtime data.

    Does not contain:
    - strategy logic;
    - risk logic;
    - execution logic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_order(self, order: dict[str, Any]) -> None:
        query = text(
            """
            INSERT INTO dds.paper_orders
            (order_id, client_order_id, symbol, side, order_type, quantity, price, status, created_at, updated_at)
            VALUES
            (:order_id, :client_order_id, :symbol, :side, :order_type, :quantity, :price, :status, :created_at, :updated_at)
            ON CONFLICT (order_id)
            DO UPDATE SET
                status = EXCLUDED.status,
                price = EXCLUDED.price,
                updated_at = EXCLUDED.updated_at
            """
        )

        now = datetime.now(timezone.utc)

        await self.session.execute(
            query,
            {
                "order_id": order["order_id"],
                "client_order_id": order.get("client_order_id"),
                "symbol": order["symbol"],
                "side": order["side"],
                "order_type": order.get("order_type", "MARKET"),
                "quantity": Decimal(str(order["quantity"])),
                "price": order.get("price"),
                "status": order["status"],
                "created_at": order.get("created_at", now),
                "updated_at": now,
            },
        )
        await self.session.commit()

    async def save_fill(self, fill: dict[str, Any]) -> None:
        query = text(
            """
            INSERT INTO dds.paper_fills
            (fill_id, order_id, symbol, quantity, price, commission, executed_at)
            VALUES
            (:fill_id, :order_id, :symbol, :quantity, :price, :commission, :executed_at)
            ON CONFLICT (fill_id)
            DO NOTHING
            """
        )

        await self.session.execute(
            query,
            {
                "fill_id": fill.get("fill_id", fill["order_id"]),
                "order_id": fill["order_id"],
                "symbol": fill["symbol"],
                "quantity": Decimal(str(fill["quantity"])),
                "price": Decimal(str(fill["price"])),
                "commission": Decimal(str(fill.get("commission", "0"))),
                "executed_at": fill.get("executed_at", datetime.now(timezone.utc)),
            },
        )
        await self.session.commit()

    async def load_orders(self) -> list[dict[str, Any]]:
        query = text(
            """
            SELECT
                order_id,
                client_order_id,
                symbol,
                side,
                order_type,
                quantity,
                price,
                status,
                created_at,
                updated_at
            FROM dds.paper_orders
            ORDER BY created_at
            """
        )

        result = await self.session.execute(query)
        return [dict(row) for row in result.mappings().all()]

    async def load_fills(self) -> list[dict[str, Any]]:
        query = text(
            """
            SELECT
                fill_id,
                order_id,
                symbol,
                quantity,
                price,
                commission,
                executed_at
            FROM dds.paper_fills
            ORDER BY executed_at
            """
        )

        result = await self.session.execute(query)
        return [dict(row) for row in result.mappings().all()]

    async def save_pnl_snapshot(self, snapshot: PaperPnLSnapshotState) -> None:
        query = text(
            """
            INSERT INTO dds.paper_pnl_snapshot
            (snapshot_time, sequence, equity, realized_pnl, unrealized_pnl,
             total_pnl, fees_paid, slippage, cash_balance, position_value,
             drawdown, drawdown_pct)
            VALUES
            (:snapshot_time, :sequence, :equity, :realized_pnl, :unrealized_pnl,
             :total_pnl, :fees_paid, :slippage, :cash_balance, :position_value,
             :drawdown, :drawdown_pct)
            ON CONFLICT (snapshot_time, sequence) DO UPDATE SET
                equity = EXCLUDED.equity,
                realized_pnl = EXCLUDED.realized_pnl,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                total_pnl = EXCLUDED.total_pnl,
                fees_paid = EXCLUDED.fees_paid,
                slippage = EXCLUDED.slippage,
                cash_balance = EXCLUDED.cash_balance,
                position_value = EXCLUDED.position_value,
                drawdown = EXCLUDED.drawdown,
                drawdown_pct = EXCLUDED.drawdown_pct
            """
        )
        await self.session.execute(query, snapshot.__dict__)
        await self.session.commit()

    async def load_pnl_snapshots(self) -> list[PaperPnLSnapshotState]:
        result = await self.session.execute(
            text(
                """
                SELECT snapshot_time, sequence, equity, realized_pnl,
                       unrealized_pnl, total_pnl, fees_paid, slippage,
                       cash_balance, position_value, drawdown, drawdown_pct
                FROM dds.paper_pnl_snapshot
                ORDER BY snapshot_time, sequence
                """
            )
        )
        return [PaperPnLSnapshotState(**dict(row)) for row in result.mappings().all()]
