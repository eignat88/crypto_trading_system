import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import structlog

from app.config.settings import TradingMode, settings
from app.exchange.base_exchange import BaseExchange, Candle, CandleBatch, Instrument
from app.exchange.exceptions import (
    ExchangeAPIRejectError,
    ExchangeAuthError,
    ExchangeRateLimitError,
    ExchangeTimeoutError,
    UnknownOrderStateError,
)
from app.exchange.intervals import interval_duration

logger = structlog.get_logger()


class BybitClient(BaseExchange):
    """Bybit V5 client with idempotency-safe order submission."""

    BASE_URLS = {
        "demo": "https://api-demo.bybit.com",
        "testnet": "https://api-testnet.bybit.com",
        "mainnet": "https://api.bybit.com",
    }
    RECV_WINDOW = 5_000
    MAX_GET_ATTEMPTS = 3
    AUTH_ERROR_CODES = {10003, 10004, 10005, 10007, 10010}
    RATE_LIMIT_CODES = {10006, 10429}
    INTERVAL_MAP = {"5m": "5", "15m": "15", "1h": "60", "4h": "240", "1d": "D"}

    def __init__(self) -> None:
        self.api_key = settings.exchange_api_key
        self.api_secret = settings.exchange_api_secret
        self.environment = settings.bybit_environment
        self.base_url = self.BASE_URLS.get(self.environment, self.BASE_URLS["demo"])
        self._live_key_checked = False
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            limits=httpx.Limits(max_connections=100),
        )

    async def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        await self.client.aclose()

    def _generate_signature(self, timestamp: int, payload: str = "") -> str:
        """Sign ``timestamp + key + recv_window + query/body`` per Bybit V5."""
        plain_text = f"{timestamp}{self.api_key}{self.RECV_WINDOW}{payload}"
        return hmac.new(self.api_secret.encode(), plain_text.encode(), hashlib.sha256).hexdigest()

    def _get_headers(self, timestamp: int, signature: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": str(self.RECV_WINDOW),
        }

    @staticmethod
    def _query_string(params: dict[str, Any] | None) -> str:
        return urlencode(sorted((params or {}).items()))

    @staticmethod
    def _json_body(body: dict[str, Any]) -> str:
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False)

    def _raise_api_error(self, data: dict[str, Any], path: str) -> None:
        code = data.get("retCode")
        if code == 0:
            return
        message = str(data.get("retMsg") or "Bybit API rejected request")
        logger.warning("bybit_api_error", code=code, msg=message, path=path)
        if code in self.AUTH_ERROR_CODES:
            raise ExchangeAuthError(message)
        if code in self.RATE_LIMIT_CODES:
            raise ExchangeRateLimitError(message)
        raise ExchangeAPIRejectError(message, code=code if isinstance(code, int) else None)

    async def _get_raw(
        self, path: str, params: dict[str, Any] | None = None, *, private: bool = False
    ) -> tuple[httpx.Response, dict[str, Any], datetime]:
        """Issue a public/private GET; only this read-only path is retried."""
        query = self._query_string(params)
        for attempt in range(self.MAX_GET_ATTEMPTS):
            timestamp = int(time.time() * 1000)
            headers = (
                self._get_headers(timestamp, self._generate_signature(timestamp, query))
                if private
                else {}
            )
            try:
                request_time = datetime.now(UTC)
                # Send the exact canonical query string that was signed. Passing the
                # original mapping could preserve a different insertion order.
                response = await self.client.get(path, params=query or None, headers=headers)
                if response.status_code == 429:
                    raise ExchangeRateLimitError("Bybit HTTP rate limit")
                if response.status_code in {401, 403}:
                    raise ExchangeAuthError("Bybit authentication failed")
                response.raise_for_status()
                data = response.json()
                self._raise_api_error(data, path)
                return response, data, request_time
            except ExchangeAuthError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                failure: Exception = ExchangeTimeoutError(str(exc))
            except ExchangeRateLimitError as exc:
                failure = exc
            except (httpx.HTTPStatusError, json.JSONDecodeError) as exc:
                raise ExchangeAPIRejectError(str(exc)) from exc
            if attempt + 1 == self.MAX_GET_ATTEMPTS:
                raise failure
            await asyncio.sleep(min(2**attempt, 4))
        raise RuntimeError("GET retry loop exited unexpectedly")

    async def _get(
        self, path: str, params: dict[str, Any] | None = None, *, private: bool = False
    ) -> dict[str, Any]:
        _, data, _ = await self._get_raw(path, params, private=private)
        return cast(dict[str, Any], data.get("result", {}))

    async def _trade_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Send a signed JSON trading request exactly once."""
        encoded = self._json_body(body)
        timestamp = int(time.time() * 1000)
        headers = self._get_headers(timestamp, self._generate_signature(timestamp, encoded))
        headers["Content-Type"] = "application/json"
        try:
            response = await self.client.post(path, content=encoded.encode(), headers=headers)
            if response.status_code == 429:
                raise ExchangeRateLimitError("Bybit HTTP rate limit")
            if response.status_code in {401, 403}:
                raise ExchangeAuthError("Bybit authentication failed")
            if response.status_code == 408 or response.status_code >= 500:
                raise ExchangeTimeoutError(
                    f"Bybit returned an indeterminate HTTP {response.status_code}"
                )
            response.raise_for_status()
            try:
                data = response.json()
            except json.JSONDecodeError as exc:
                raise ExchangeTimeoutError("Bybit returned an indeterminate response") from exc
            self._raise_api_error(data, path)
            return cast(dict[str, Any], data.get("result", {}))
        except (
            ExchangeAuthError,
            ExchangeRateLimitError,
            ExchangeAPIRejectError,
            ExchangeTimeoutError,
        ):
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ExchangeTimeoutError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            raise ExchangeAPIRejectError(str(exc)) from exc

    async def _ensure_live_key_safe(self) -> None:
        if settings.trading_mode != TradingMode.LIVE or self._live_key_checked:
            return
        key_info = await self._get("/v5/user/query-api", private=True)
        wallet_permissions = key_info.get("permissions", {}).get("Wallet", [])
        if any("withdraw" in permission.lower() for permission in wallet_permissions):
            raise ExchangeAuthError("Live API key must not have withdrawal permission")
        self._live_key_checked = True

    async def get_instruments(self) -> list[Instrument]:
        result = await self._get("/v5/market/instruments-info", {"category": "spot"})
        return [
            Instrument(i["symbol"], i["baseCoin"], i["quoteCoin"], i["status"] == "Trading")
            for i in result.get("list", [])
        ]

    async def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[Candle]:
        duration = interval_duration(interval)
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": self.INTERVAL_MAP.get(interval, interval),
            "start": int(start_time.timestamp() * 1000),
            "end": int(end_time.timestamp() * 1000),
            "limit": min(limit, 1000),
        }
        response, payload, request_time = await self._get_raw("/v5/market/kline", params)
        candles: list[Candle] = []
        for item in payload.get("result", {}).get("list", []):
            open_time = datetime.fromtimestamp(int(item[0]) / 1000, tz=UTC)
            candles.append(
                Candle(
                    "bybit",
                    symbol,
                    interval,
                    open_time,
                    open_time + duration,
                    Decimal(item[1]),
                    Decimal(item[2]),
                    Decimal(item[3]),
                    Decimal(item[4]),
                    Decimal(item[5]),
                    Decimal(item[6]) if item[6] else None,
                    None,
                    item,
                )
            )
        candles.sort(key=lambda candle: candle.open_time)
        return CandleBatch(
            candles,
            request_id=response.headers.get("Traceid") or response.headers.get("X-Request-Id"),
            request_time=request_time,
            request_payload=params,
            response_payload=payload,
        )

    async def get_current_price(self, symbol: str) -> Decimal:
        tickers = (
            await self._get("/v5/market/tickers", {"category": "spot", "symbol": symbol})
        ).get("list", [])
        if not tickers:
            raise ExchangeAPIRejectError(f"No ticker found for {symbol}")
        return Decimal(tickers[0]["lastPrice"])

    async def get_balance(self) -> dict[str, Decimal]:
        result = await self._get(
            "/v5/account/wallet-balance", {"accountType": "UNIFIED"}, private=True
        )
        return {
            coin["coin"]: Decimal(coin["walletBalance"])
            for coin in result.get("list", [{}])[0].get("coin", [])
        }

    async def get_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"category": "spot", "orderStatus": "New"}
        if symbol:
            params["symbol"] = symbol
        orders = (await self._get("/v5/order/realtime", params, private=True)).get("list", [])
        return cast(list[dict[str, Any]], orders)

    async def get_order_by_client_id(self, client_order_id: str) -> dict[str, Any] | None:
        result = await self._get(
            "/v5/order/realtime", {"category": "spot", "orderLinkId": client_order_id}, private=True
        )
        orders = cast(list[dict[str, Any]], result.get("list", []))
        return orders[0] if orders else None

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        client_order_id: str,
        price: Decimal | None = None,
    ) -> dict[str, Any]:
        if not client_order_id or not client_order_id.strip():
            raise ValueError("client_order_id is required for every order")
        await self._ensure_live_key_safe()
        body = {
            "category": "spot",
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(quantity),
            "orderLinkId": client_order_id,
        }
        if price is not None:
            body["price"] = str(price)
        try:
            return await self._trade_post("/v5/order/create", body)
        except ExchangeTimeoutError:
            try:
                existing = await self.get_order_by_client_id(client_order_id)
            except Exception as lookup_error:
                raise UnknownOrderStateError(client_order_id) from lookup_error
            if existing is not None:
                return existing
            raise UnknownOrderStateError(client_order_id)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        await self._ensure_live_key_safe()
        return await self._trade_post("/v5/order/cancel", {"category": "spot", "orderId": order_id})

    async def get_executions(
        self, symbol: str | None = None, start_time: datetime | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": "spot"}
        if symbol:
            params["symbol"] = symbol
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        executions = (await self._get("/v5/execution/list", params, private=True)).get("list", [])
        return cast(list[dict[str, Any]], executions)

    async def health_check(self) -> bool:
        try:
            await self._get("/v5/market/time")
            return True
        except Exception as exc:
            logger.error("health_check_failed", error=str(exc))
            return False
