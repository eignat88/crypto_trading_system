from __future__ import annotations

from decimal import Decimal

import pytest

from app.exchange.paper_exchange import PaperExchange
from app.exchange.paper_repository import PaperRepository


@pytest.mark.asyncio
async def test_paper_exchange_persists_order_and_fill() -> None:
    repository = PaperRepository()
    exchange = PaperExchange(repository=repository)

    order = await exchange.place_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.1"),
        client_order_id="paper-test-1",
    )

    fill = await exchange.execute_order(
        order_id=order["order_id"],
        market_price=Decimal("60000"),
    )

    assert len(repository.orders) == 1
    assert repository.orders[0]["order_id"] == order["order_id"]

    assert len(repository.fills) == 1
    assert repository.fills[0]["order_id"] == fill["order_id"]
