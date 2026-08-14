from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.database.repositories.postgres_paper_repository import (
    PostgresPaperRepository,
)


@pytest.mark.asyncio
async def test_save_order_executes_insert_query() -> None:
    session = AsyncMock()
    repository = PostgresPaperRepository(session)

    order = {
        "order_id": "order-001",
        "client_order_id": "client-001",
        "symbol": "BTCUSDT",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": "0.01",
        "price": "60000",
        "status": "FILLED",
        "created_at": datetime.now(UTC),
    }

    await repository.save_order(order)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()

    params = session.execute.await_args.args[1]

    assert params["order_id"] == "order-001"
    assert params["symbol"] == "BTCUSDT"
    assert params["quantity"] == Decimal("0.01")


@pytest.mark.asyncio
async def test_save_fill_executes_insert_query() -> None:
    session = AsyncMock()
    repository = PostgresPaperRepository(session)

    fill = {
        "fill_id": "fill-001",
        "order_id": "order-001",
        "symbol": "BTCUSDT",
        "quantity": "0.01",
        "price": "60000",
        "commission": "0.1",
        "executed_at": datetime.now(UTC),
    }

    await repository.save_fill(fill)

    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()

    params = session.execute.await_args.args[1]

    assert params["fill_id"] == "fill-001"
    assert params["order_id"] == "order-001"
    assert params["commission"] == Decimal("0.1")
