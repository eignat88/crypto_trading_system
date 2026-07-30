import asyncio
import hashlib
import hmac
from decimal import Decimal
from functools import wraps

import httpx
import pytest

from app.exchange.bybit_client import BybitClient
from app.exchange.exceptions import ExchangeTimeoutError, UnknownOrderStateError


def async_test(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def test_v5_signature_contains_recv_window() -> None:
    client = BybitClient()
    client.api_key = "key"
    client.api_secret = "secret"
    expected = hmac.new(b"secret", b"123key5000category=spot", hashlib.sha256).hexdigest()

    assert client._generate_signature(123, "category=spot") == expected


@async_test
async def test_trade_post_signs_and_sends_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BybitClient()
    client.api_key = "key"
    client.api_secret = "secret"
    seen: dict = {}

    async def post(path: str, **kwargs: object) -> httpx.Response:
        seen.update(path=path, **kwargs)
        return httpx.Response(
            200,
            json={"retCode": 0, "result": {"orderId": "1"}},
            request=httpx.Request("POST", "https://api.bybit.com" + path),
        )

    monkeypatch.setattr(client.client, "post", post)
    result = await client._trade_post("/v5/order/create", {"symbol": "BTCUSDT"})

    assert result == {"orderId": "1"}
    assert seen["content"] == b'{"symbol":"BTCUSDT"}'
    assert "params" not in seen
    headers = seen["headers"]
    timestamp = int(headers["X-BAPI-TIMESTAMP"])
    assert headers["X-BAPI-SIGN"] == client._generate_signature(timestamp, '{"symbol":"BTCUSDT"}')


@async_test
async def test_order_timeout_is_reconciled_without_resubmission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BybitClient()
    calls = 0

    async def trade_post(path: str, body: dict) -> dict:
        nonlocal calls
        calls += 1
        raise ExchangeTimeoutError("timeout")

    async def lookup(client_order_id: str) -> dict:
        return {"orderId": "exchange-id", "orderLinkId": client_order_id}

    monkeypatch.setattr(client, "_trade_post", trade_post)
    monkeypatch.setattr(client, "get_order_by_client_id", lookup)

    result = await client.place_order("BTCUSDT", "Buy", "Market", Decimal("1"), "unique-id")
    assert result["orderId"] == "exchange-id"
    assert calls == 1


@async_test
async def test_order_timeout_with_no_match_has_unknown_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = BybitClient()

    async def trade_post(path: str, body: dict) -> dict:
        raise ExchangeTimeoutError("timeout")

    async def lookup(client_order_id: str) -> None:
        return None

    monkeypatch.setattr(client, "_trade_post", trade_post)
    monkeypatch.setattr(client, "get_order_by_client_id", lookup)

    with pytest.raises(UnknownOrderStateError):
        await client.place_order("BTCUSDT", "Buy", "Market", Decimal("1"), "unique-id")


@async_test
async def test_client_order_id_is_required() -> None:
    client = BybitClient()
    with pytest.raises(ValueError, match="client_order_id"):
        await client.place_order("BTCUSDT", "Buy", "Market", Decimal("1"), "")
