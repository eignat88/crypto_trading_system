"""
Collect Market Data Script.

This script collects market data from Bybit and stores it in PostgreSQL.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from app.collectors.bybit_market_data import BybitMarketDataCollector

# Configure logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger("INFO"),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def main():
    """Run the market data collector."""
    print("=" * 60)
    print("Bybit Market Data Collector")
    print("=" * 60)
    print()
    print("Press Ctrl+C to stop")
    print()

    collector = BybitMarketDataCollector()
    await collector.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
