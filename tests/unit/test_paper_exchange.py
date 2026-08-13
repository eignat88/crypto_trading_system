from decimal import Decimal

import pytest

from app.exchange.paper_exchange import PaperExchange


@pytest.mark.asyncio
async def test_paper_exchange_creates_order():
    exchange = PaperExchange()

    result = await exchange.place_order(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("0.01"),
        client_order_id="test-001",
    )

    assert result["client_order_id"] == "test-001"
    assert result["status"] == "NEW"


@pytest.mark.asyncio
async def test_health_check():
    exchange = PaperExchange()
    assert await exchange.health_check() is True
