#!/usr/bin/env python3
"""Backfill historical candles for paper trading.

Usage:
    python scripts/backfill_history.py                    # default 500 candles
    python scripts/backfill_history.py --candles 1000     # load 1000 candles
    python scripts/backfill_history.py --symbols BTCUSDT  # specific symbol
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def backfill(symbols: list[str], target_candles: int) -> None:
    """Backfill historical candles."""
    from app.config.settings import Settings
    from app.exchange.bybit_client import BybitClient
    from app.exchange.bybit_paper_market_data import BybitPaperMarketData
    from app.collectors.candle_collector import CandleCollector
    import asyncpg

    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url_sync, min_size=1, max_size=2)
    bybit = BybitClient()
    collector = CandleCollector(bybit)

    market_data = BybitPaperMarketData(
        pool=pool,
        collector=collector,
        symbols=symbols,
        interval=settings.paper_market_interval,
        warmup_candles=target_candles,
        backfill_buffer=100,
        poll_seconds=settings.paper_market_poll_seconds,
        stale_grace_seconds=settings.paper_market_stale_grace_seconds,
    )

    print(f"Backfilling {target_candles} candles for {', '.join(symbols)}...")
    counts = await market_data.bootstrap()

    print("\nResults:")
    for symbol, count in counts.items():
        status = "OK" if count >= target_candles else f"INSUFFICIENT ({count} < {target_candles})"
        print(f"  {symbol}: {count} candles - {status}")

    await bybit.close()
    await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candles", type=int, default=500, help="Target candle count")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    args = parser.parse_args()

    asyncio.run(backfill(args.symbols, args.candles))


if __name__ == "__main__":
    main()
