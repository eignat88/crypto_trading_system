"""Run the idempotent RAW -> DDS candle pipeline and print its report."""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import async_session_factory  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load closed RAW candles into DDS")
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--symbol", choices=("BTCUSDT", "ETHUSDT"))
    parser.add_argument("--interval")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    async with async_session_factory() as session, session.begin():
        result = await session.execute(
            text(
                """
                SELECT * FROM dds.load_raw_candles(
                    :exchange, :symbol, :interval, clock_timestamp()
                )
                """
            ),
            {"exchange": args.exchange, "symbol": args.symbol, "interval": args.interval},
        )
        rows = result.mappings().all()

    if not rows:
        print("No matching RAW candle streams found.")
        return
    for row in rows:
        print(
            f"run={row['run_id']} {row['exchange_name']} {row['symbol']} "
            f"{row['interval_code']}: source={row['source_count']} "
            f"inserted={row['inserted_count']} rejected={row['rejected_count']} "
            f"deferred={row['deferred_count']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
