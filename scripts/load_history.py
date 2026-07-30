"""
Script to load historical candle data into PostgreSQL.

Usage:
    python scripts/load_history.py --symbol BTCUSDT --interval 1d --years 3
    python scripts/load_history.py --symbol ETHUSDT --interval 1h --start 2021-01-01
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

# Add project root to path
sys_path = Path(__file__).parent.parent
import sys  # noqa: E402

sys.path.insert(0, str(sys_path))

from app.collectors.candle_collector import CandleCollector, interval_duration  # noqa: E402
from app.exchange.bybit_client import BybitClient  # noqa: E402

# Configure logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger("info"),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Default symbols and intervals
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
INTERVALS = ["5m", "15m", "1h", "4h", "1d"]


def parse_args():
    parser = argparse.ArgumentParser(description="Load historical candle data")
    parser.add_argument(
        "--symbol",
        nargs="+",
        default=SYMBOLS,
        help="Symbols to load (default: BTCUSDT ETHUSDT)",
    )
    parser.add_argument(
        "--interval",
        nargs="+",
        default=INTERVALS,
        help="Intervals to load (default: 5m 15m 1h 4h 1d)",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=3,
        help="Years of history to load (default: 3)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Overrides --years",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Default: now",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # Calculate date range
    end_date = datetime.now(UTC)
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)

    start_date = end_date - timedelta(days=args.years * 365)
    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)

    logger.info(
        "loading_config",
        symbols=args.symbol,
        intervals=args.interval,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
    )

    # Initialize exchange client
    exchange = BybitClient()
    collector = CandleCollector(exchange)

    try:
        for symbol in args.symbol:
            for interval in args.interval:
                logger.info(
                    "loading_started",
                    symbol=symbol,
                    interval=interval,
                )

                # Check for resume point
                current_start = start_date
                if args.resume:
                    checkpoint = await collector.get_last_checkpoint(symbol, interval)
                    if checkpoint:
                        current_start = checkpoint + interval_duration(interval)
                        logger.info(
                            "resuming_from_checkpoint",
                            symbol=symbol,
                            interval=interval,
                            checkpoint=checkpoint.isoformat(),
                        )

                # Load candles
                total_loaded = await collector.load_historical_candles(
                    symbol=symbol,
                    interval=interval,
                    start_date=current_start,
                    end_date=end_date,
                )

                logger.info(
                    "loading_completed",
                    symbol=symbol,
                    interval=interval,
                    total_loaded=total_loaded,
                )

    finally:
        await exchange.close()

    logger.info("all_loading_completed")


if __name__ == "__main__":
    asyncio.run(main())
