"""Calculate and persist technical indicators and market regimes for DDS candles."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.collectors.indicator_batch_collector import BatchIndicatorCollector  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate EMA/RSI/ATR/volatility and market regime"
    )
    parser.add_argument(
        "--symbol",
        nargs="+",
        choices=("BTCUSDT", "ETHUSDT"),
        default=["BTCUSDT", "ETHUSDT"],
    )
    parser.add_argument("--interval", default="1h")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    collector = BatchIndicatorCollector()

    for symbol in args.symbol:
        processed = await collector.calculate_and_store_indicators(
            symbol=symbol,
            interval=args.interval,
        )
        print(f"{symbol} {args.interval}: processed={processed}")


if __name__ == "__main__":
    asyncio.run(main())
