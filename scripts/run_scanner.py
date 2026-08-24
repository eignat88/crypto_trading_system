#!/usr/bin/env python3
"""CLI script to run the crypto setup scanner.

Usage:
    python scripts/run_scanner.py
    python scripts/run_scanner.py --timeframe 1h --top 10
    python scripts/run_scanner.py --output artifacts/scanner.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.scanner.models import SCANNER_VERSION
from app.scanner.scanner import ScannerEngine
from app.scanner.scoring import ScoringWeights
from app.scanner.universe import UniverseConfig
from app.setups.base import CandleData, IndicatorSnapshot

BYBIT_BASE_URL = "https://api.bybit.com"


async def fetch_candles(symbol: str, interval: str = "1h", limit: int = 300) -> list[CandleData]:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BYBIT_BASE_URL}/v5/market/kline",
            params={"category": "spot", "symbol": symbol, "interval": interval, "limit": limit},
            timeout=10.0,
        )
        data = response.json()
        if data["retCode"] != 0:
            return []
        candles = []
        for item in data["result"]["list"]:
            candles.append(CandleData(
                symbol=symbol,
                open_time=datetime.fromtimestamp(int(item[0]) / 1000, tz=UTC),
                open=Decimal(item[1]),
                high=Decimal(item[2]),
                low=Decimal(item[3]),
                close=Decimal(item[4]),
                volume=Decimal(item[5]),
            ))
        candles.sort(key=lambda c: c.open_time)
        return candles


def calculate_ema(prices: list[Decimal], period: int) -> Decimal | None:
    if len(prices) < period:
        return None
    multiplier = Decimal(2) / Decimal(period + 1)
    ema = sum(prices[:period]) / Decimal(period)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calculate_atr(candles: list[CandleData], period: int = 14) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    true_ranges = []
    for i in range(1, len(candles)):
        hl = candles[i].high - candles[i].low
        hc = abs(candles[i].high - candles[i - 1].close)
        lc = abs(candles[i].low - candles[i - 1].close)
        true_ranges.append(max(hl, hc, lc))
    atr = sum(true_ranges[:period]) / Decimal(period)
    for tr in true_ranges[period:]:
        atr = (atr * Decimal(period - 1) + tr) / Decimal(period)
    return atr


def compute_indicators(candles: list[CandleData]) -> IndicatorSnapshot:
    closes = [c.close for c in candles]
    volumes = [c.volume for c in candles]
    return IndicatorSnapshot(
        ema20=calculate_ema(closes, 20),
        ema50=calculate_ema(closes, 50),
        ema200=calculate_ema(closes, 200),
        atr=calculate_atr(candles, 14),
        volume_ma20=sum(volumes[-20:]) / Decimal(20) if len(volumes) >= 20 else None,
    )


def format_table(results, top_n=None):
    if top_n:
        results = results[:top_n]
    lines = [
        "=" * 70,
        "Crypto Setup Scanner",
        "=" * 70,
        "",
        f"{'Symbol':<12} {'Score':>6} {'Setup':<18} {'Direction':<15}",
        "-" * 70,
    ]
    for r in results:
        lines.append(f"{r.symbol:<12} {r.score:>6} {r.setup_type.value:<18} {r.direction.value:<15}")
    lines.append("-" * 70)
    lines.append(f"Signals: {len(results)}")
    lines.append("=" * 70)
    return "\n".join(lines)


def format_json(results, scan_time, symbols_scanned):
    return {
        "scan_time": scan_time.isoformat(),
        "timeframe": "1h",
        "scanner_version": SCANNER_VERSION,
        "symbols_scanned": symbols_scanned,
        "signals": [
            {
                "symbol": r.symbol,
                "setup": r.setup_type.value,
                "direction": r.direction.value,
                "score": float(r.score),
                "price": float(r.current_price),
                "detected_at": r.detected_at.isoformat(),
                "metadata": r.metadata,
            }
            for r in results
        ],
    }


async def main():
    parser = argparse.ArgumentParser(description="Crypto Setup Scanner")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--top", type=int)
    parser.add_argument("--output", help="Output JSON file path")
    parser.add_argument("--symbols", nargs="+")
    args = parser.parse_args()

    start_time = time.time()
    universe = UniverseConfig(symbols=args.symbols, timeframe=args.timeframe) if args.symbols else UniverseConfig(timeframe=args.timeframe)

    print(f"\nScanning {len(universe.symbols)} symbols on {args.timeframe} timeframe...\n")

    candle_data = {}
    indicators = {}
    for symbol in universe.symbols:
        candles = await fetch_candles(symbol, args.timeframe, limit=300)
        if len(candles) >= universe.min_candles:
            candle_data[symbol] = candles
            indicators[symbol] = compute_indicators(candles)
        else:
            print(f"  {symbol}: insufficient data ({len(candles)} candles)")

    scanner = ScannerEngine(universe=universe)
    results = scanner.scan(candle_data, indicators)

    scan_time = datetime.now(UTC)
    duration = time.time() - start_time

    if args.output:
        output = format_json(results, len(candle_data), scan_time)
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to {args.output}")
    else:
        print(format_table(results, args.top))
        print(f"\nDuration: {duration:.1f} sec")


if __name__ == "__main__":
    asyncio.run(main())
