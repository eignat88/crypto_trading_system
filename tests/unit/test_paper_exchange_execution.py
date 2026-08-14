from decimal import Decimal

import pytest

from app.exchange.paper_exchange import PaperExchange


@pytest.mark.asyncio
async def test_paper_exchange_executes_market_order_when_price_available() -> None:
    exchange = PaperExchange()

    order = await exchange.place_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.1"),
        client_order_id="paper-test-001",
        price=Decimal("60000"),
    )

    assert order["status"] == "NEW"

    execution = await exchange.execute_order(
        order["order_id"],
        Decimal("60000"),
    )

    assert execution["status"] == "FILLED"
    assert execution["price"] == Decimal("60000")

    assert len(exchange.state.executions) == 1
