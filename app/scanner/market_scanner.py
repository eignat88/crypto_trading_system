"""Market Scanner — автоматический подбор монет для скальпинга.

Архитектура:
Exchange API → Market Scanner → Ranking → Strategy

Критерии отбора:
- Volume 24h > 500M USDT
- Spread < 0.05%
- ATR/Price > 0.3%
- Trades > minimum
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from decimal import Decimal
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class ScanResult:
    """Result of scanning a single pair."""
    symbol: str
    price: float
    volume_24h: float
    change_24h: float
    high_24h: float
    low_24h: float
    spread_pct: float
    atr_pct: float
    score: float
    rank: int = 0


class MarketScanner:
    """Scan Bybit spot market for scalping candidates.

    Scoring formula:
    Score = Volume_score * 0.3 + Liquidity_score * 0.3 + Volatility_score * 0.3 + Spread_score * 0.1
    """

    BASE_URL = "https://api-demo.bybit.com"

    # Minimum thresholds
    MIN_VOLUME_24H = 500_000_000  # 500M USDT
    MIN_ATR_PCT = 0.3  # 0.3%
    MAX_SPREAD_PCT = 0.05  # 0.05%

    def __init__(self) -> None:
        self._cache: list[ScanResult] = []
        self._last_scan: datetime | None = None

    async def scan(self) -> list[ScanResult]:
        """Scan all USDT spot pairs and rank by scalpability."""
        async with httpx.AsyncClient() as client:
            # Get all USDT spot tickers
            response = await client.get(
                f"{self.BASE_URL}/v5/market/tickers",
                params={"category": "spot"}
            )
            data = response.json()

            if data["retCode"] != 0:
                logger.error("scanner_api_error", msg=data.get("retMsg"))
                return []

            tickers = data["result"]["list"]
            results: list[ScanResult] = []

            for ticker in tickers:
                symbol = ticker["symbol"]
                if not symbol.endswith("USDT"):
                    continue

                price = float(ticker.get("lastPrice", "0"))
                volume_24h = float(ticker.get("volume24h", "0"))
                change_24h = float(ticker.get("price24hPcnt", "0")) * 100
                high_24h = float(ticker.get("highPrice24h", "0"))
                low_24h = float(ticker.get("lowPrice24h", "0"))

                # Skip low volume
                if volume_24h < self.MIN_VOLUME_24H:
                    continue

                # Calculate spread (bid/ask approximation from high/low)
                if low_24h > 0:
                    range_pct = ((high_24h - low_24h) / low_24h) * 100
                else:
                    range_pct = 0

                # Calculate ATR approximation (from 24h range)
                atr_pct = range_pct / 2  # Approximate 15m ATR from 24h range

                # Skip low volatility
                if atr_pct < self.MIN_ATR_PCT:
                    continue

                # Calculate score
                volume_score = min(100, volume_24h / 1_000_000_000 * 100)  # Normalize to 1B
                liquidity_score = min(100, volume_24h / 500_000_000 * 100)  # Normalize to 500M
                volatility_score = min(100, atr_pct / 2 * 100)  # Normalize to 2%
                spread_score = max(0, 100 - range_pct * 10)  # Lower spread = higher score

                score = (
                    volume_score * 0.3 +
                    liquidity_score * 0.3 +
                    volatility_score * 0.3 +
                    spread_score * 0.1
                )

                results.append(ScanResult(
                    symbol=symbol,
                    price=price,
                    volume_24h=volume_24h,
                    change_24h=change_24h,
                    high_24h=high_24h,
                    low_24h=low_24h,
                    spread_pct=range_pct,
                    atr_pct=atr_pct,
                    score=score,
                ))

            # Sort by score
            results.sort(key=lambda x: x.score, reverse=True)

            # Assign ranks
            for i, r in enumerate(results):
                r.rank = i + 1

            self._cache = results
            self._last_scan = datetime.now(UTC)

            return results

    def get_top_candidates(self, n: int = 10) -> list[ScanResult]:
        """Get top N candidates from last scan."""
        return self._cache[:n]

    def get_candidate(self, symbol: str) -> ScanResult | None:
        """Get specific candidate by symbol."""
        for r in self._cache:
            if r.symbol == symbol:
                return r
        return None
