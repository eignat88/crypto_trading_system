import time
import hmac
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from urllib.parse import urlencode

import httpx
import structlog

from app.exchange.base_exchange import BaseExchange, Candle, Instrument
from app.config.settings import settings

logger = structlog.get_logger()


class BybitClient(BaseExchange):
    """Bybit exchange client implementation."""

    BASE_URL = "https://api.bybit.com"

    # Interval mapping
    INTERVAL_MAP = {
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "D",
    }

    def __init__(self):
        self.api_key = settings.exchange_api_key
        self.api_secret = settings.exchange_api_secret
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            limits=httpx.Limits(max_connections=100),
        )

    def _generate_signature(
        self, timestamp: int, params: Optional[dict] = None, body: str = ""
    ) -> str:
        """Generate HMAC signature for authenticated requests."""
        param_str = ""
        if params:
            param_str = urlencode(sorted(params.items()))
        
        sign_str = f"{timestamp}{self.api_key}{param_str}{body}"
        return hmac.new(
            self.api_secret.encode(), sign_str.encode(), hashlib.sha256
        ).hexdigest()

    def _get_headers(self, timestamp: int, sign: str) -> dict:
        return {
            "X-BAPI-API-KEY": self.api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": str(timestamp),
            "X-BAPI-RECV-WINDOW": "5000",
        }

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        authenticated: bool = False,
    ) -> dict:
        """Make API request with retry logic."""
        for attempt in range(3):
            try:
                timestamp = int(time.time() * 1000)
                headers = {}
                
                if authenticated:
                    sign = self._generate_signature(timestamp, params)
                    headers = self._get_headers(timestamp, sign)

                response = await self.client.request(
                    method, path, params=params, headers=headers
                )
                response.raise_for_status()
                data = response.json()
                
                if data.get("retCode") != 0:
                    logger.warning(
                        "bybit_api_error",
                        code=data.get("retCode"),
                        msg=data.get("retMsg"),
                        path=path,
                    )
                    raise ValueError(f"Bybit API error: {data.get('retMsg')}")
                
                return data.get("result", {})
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:  # Rate limit
                    wait_time = min(2 ** attempt * 1000, 10000)
                    logger.warning("rate_limit_hit", wait_ms=wait_time)
                    import asyncio
                    await asyncio.sleep(wait_time / 1000)
                    continue
                raise
            except Exception as e:
                if attempt == 2:
                    raise
                logger.warning("request_retry", attempt=attempt + 1, error=str(e))
                import asyncio
                await asyncio.sleep(1)
                continue

    async def get_instruments(self) -> list[Instrument]:
        """Get list of available instruments."""
        result = await self._request("GET", "/v5/market/instruments-info", {"category": "spot"})
        
        instruments = []
        for item in result.get("list", []):
            instruments.append(
                Instrument(
                    symbol=item["symbol"],
                    base_currency=item["baseCoin"],
                    quote_currency=item["quoteCoin"],
                    is_active=item["status"] == "Trading",
                )
            )
        return instruments

    async def get_candles(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1000,
    ) -> list[Candle]:
        """Get historical candles."""
        interval_code = self.INTERVAL_MAP.get(interval, interval)
        
        params = {
            "category": "spot",
            "symbol": symbol,
            "interval": interval_code,
            "start": int(start_time.timestamp() * 1000),
            "end": int(end_time.timestamp() * 1000),
            "limit": min(limit, 1000),
        }
        
        result = await self._request("GET", "/v5/market/kline", params)
        
        candles = []
        for item in result.get("list", []):
            # Bybit returns: [startTime, open, high, low, close, volume, turnover]
            open_time = datetime.fromtimestamp(int(item[0]) / 1000, tz=timezone.utc)
            
            candles.append(
                Candle(
                    exchange_name="bybit",
                    symbol=symbol,
                    interval_code=interval,
                    open_time=open_time,
                    close_time=None,  # Will be calculated
                    open_price=Decimal(item[1]),
                    high_price=Decimal(item[2]),
                    low_price=Decimal(item[3]),
                    close_price=Decimal(item[4]),
                    volume=Decimal(item[5]),
                    quote_volume=Decimal(item[6]) if item[6] else None,
                    trade_count=None,
                )
            )
        
        return candles

    async def get_current_price(self, symbol: str) -> Decimal:
        """Get current price for a symbol."""
        result = await self._request(
            "GET", "/v5/market/tickers", {"category": "spot", "symbol": symbol}
        )
        
        tickers = result.get("list", [])
        if not tickers:
            raise ValueError(f"No ticker found for {symbol}")
        
        return Decimal(tickers[0]["lastPrice"])

    async def get_balance(self) -> dict[str, Decimal]:
        """Get account balance."""
        result = await self._request(
            "GET", "/v5/account/wallet-balance", {"accountType": "UNIFIED"}, authenticated=True
        )
        
        balances = {}
        for coin in result.get("list", [{}])[0].get("coin", []):
            balances[coin["coin"]] = Decimal(coin["walletBalance"])
        
        return balances

    async def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """Get open orders."""
        params = {"category": "spot", "orderStatus": "New"}
        if symbol:
            params["symbol"] = symbol
        
        result = await self._request("GET", "/v5/order/realtime", params, authenticated=True)
        return result.get("list", [])

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Place a new order."""
        params = {
            "category": "spot",
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(quantity),
        }
        
        if price is not None:
            params["price"] = str(price)
        
        if client_order_id:
            params["orderLinkId"] = client_order_id
        
        return await self._request("POST", "/v5/order/create", params, authenticated=True)

    async def cancel_order(self, order_id: str) -> dict:
        """Cancel an order."""
        params = {
            "category": "spot",
            "orderId": order_id,
        }
        return await self._request("POST", "/v5/order/cancel", params, authenticated=True)

    async def get_executions(
        self,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
    ) -> list[dict]:
        """Get trade executions."""
        params = {"category": "spot"}
        if symbol:
            params["symbol"] = symbol
        if start_time:
            params["startTime"] = int(start_time.timestamp() * 1000)
        
        result = await self._request("GET", "/v5/execution/list", params, authenticated=True)
        return result.get("list", [])

    async def health_check(self) -> bool:
        """Check if exchange API is available."""
        try:
            await self._request("GET", "/v5/market/time")
            return True
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            return False

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()
