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

    assert order["status"] == "FILLED"

    executions = await exchange.get_executions()

    assert len(executions) == 1
    assert executions[0]["symbol"] == "BTCUSDT"
    assert executions[0]["quantity"] == Decimal("0.1")
    assert executions[0]["price"] == Decimal("60000")
