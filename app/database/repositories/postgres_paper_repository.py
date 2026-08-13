from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresPaperRepository:
    """
    PostgreSQL persistence adapter for Paper Trading runtime.

    Responsibility:
    - persist paper orders;
    - persist paper fills.

    Does not contain:
    - strategy logic;
    - risk logic;
    - execution logic.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_order(
        self,
        order: dict[str, Any],
    ) -> None:
        """
        Save paper order.

        Idempotent by order_id.
        Existing order gets updated.
        """

        query = text(
            """
            INSERT INTO dds.paper_orders
            (
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
            )
            VALUES
            (
                :order_id,
                :client_order_id,
                :symbol,
                :side,
                :order_type,
                :quantity,
                :price,
                :status,
                :created_at,
                :updated_at
            )
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
                "client_order_id": order.get(
                    "client_order_id"
                ),
                "symbol": order["symbol"],
                "side": order["side"],
                "order_type": order.get(
                    "order_type",
                    "MARKET",
                ),
                "quantity": Decimal(
                    str(order["quantity"])
                ),
                "price": order.get("price"),
                "status": order["status"],
                "created_at": order.get(
                    "created_at",
                    now,
                ),
                "updated_at": now,
            },
        )

        await self.session.commit()

    async def save_fill(
        self,
        fill: dict[str, Any],
    ) -> None:
        """
        Save paper execution fill.

        Duplicate fill_id is ignored.
        """

        query = text(
            """
            INSERT INTO dds.paper_fills
            (
                fill_id,
                order_id,
                symbol,
                quantity,
                price,
                commission,
                executed_at
            )
            VALUES
            (
                :fill_id,
                :order_id,
                :symbol,
                :quantity,
                :price,
                :commission,
                :executed_at
            )
            ON CONFLICT (fill_id)
            DO NOTHING
            """
        )

        await self.session.execute(
            query,
            {
                "fill_id": fill.get(
                    "fill_id",
                    fill["order_id"],
                ),
                "order_id": fill["order_id"],
                "symbol": fill["symbol"],
                "quantity": Decimal(
                    str(fill["quantity"])
                ),
                "price": Decimal(
                    str(fill["price"])
                ),
                "commission": Decimal(
                    str(
                        fill.get(
                            "commission",
                            "0",
                        )
                    )
                ),
                "executed_at": fill.get(
                    "executed_at",
                    datetime.now(timezone.utc),
                ),
            },
        )

        await self.session.commit()