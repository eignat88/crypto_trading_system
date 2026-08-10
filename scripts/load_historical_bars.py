"""
Load Historical Bars Script using NautilusTrader.

This script loads historical candle data from Bybit via NautilusTrader
and stores it in PostgreSQL (raw_bybit.bars).

Usage:
    python scripts/load_historical_bars.py --symbol BTCUSDT --interval 1h --days 30
    python scripts/load_historical_bars.py --symbol ETHUSDT --interval 1d --start 2024-01-01
"""

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg
from app.config.settings import settings

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

# Interval mapping for NautilusTrader
INTERVAL_MAP = {
    "1m": "1-MINUTE",
    "5m": "5-MINUTE",
    "15m": "15-MINUTE",
    "1h": "1-HOUR",
    "4h": "4-HOUR",
    "1d": "1-DAY",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Load historical bars from Bybit")
    parser.add_argument(
        "--symbol",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        help="Symbols to load (default: BTCUSDT ETHUSDT)",
    )
    parser.add_argument(
        "--interval",
        default="1h",
        help="Interval (default: 1h)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of history to load (default: 30)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Overrides --days",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Default: now",
    )
    return parser.parse_args()


def store_bars_to_postgres(bars: list, symbol: str, interval: str) -> int:
    """Store bars to PostgreSQL raw_bybit.bars table."""
    conn = psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )

    try:
        with conn.cursor() as cur:
            inserted = 0
            for bar in bars:
                try:
                    cur.execute("""
                        INSERT INTO raw_bybit.bars (
                            instrument_id, bar_type, ts_event, ts_init,
                            open_price, high_price, low_price, close_price, volume,
                            raw_payload
                        ) VALUES (
                            %s, %s, %s, %s,
                            %s, %s, %s, %s, %s,
                            %s
                        )
                        ON CONFLICT (instrument_id, bar_type, ts_event) DO NOTHING
                    """, (
                        f"{symbol}-SPOT.BYBIT",
                        f"{symbol}-SPOT.BYBIT-{INTERVAL_MAP[interval]}-LAST-EXTERNAL",
                        bar.ts_event,
                        bar.ts_init,
                        Decimal(str(bar.open)),
                        Decimal(str(bar.high)),
                        Decimal(str(bar.low)),
                        Decimal(str(bar.close)),
                        Decimal(str(bar.volume)),
                        None,  # raw_payload
                    ))
                    if cur.rowcount > 0:
                        inserted += 1
                except Exception as e:
                    logger.warning("bar_store_error", error=str(e), bar=str(bar))

            conn.commit()
            return inserted

    finally:
        conn.close()


async def load_bars_via_nautilus(
    symbol: str,
    interval: str,
    start_date: datetime,
    end_date: datetime,
) -> list:
    """Load bars using NautilusTrader."""
    from nautilus_trader.adapters.bybit import BYBIT
    from nautilus_trader.adapters.bybit import BybitDataClientConfig
    from nautilus_trader.adapters.bybit import BybitEnvironment
    from nautilus_trader.adapters.bybit import BybitLiveDataClientFactory
    from nautilus_trader.adapters.bybit import BybitProductType
    from nautilus_trader.config import InstrumentProviderConfig
    from nautilus_trader.config import LoggingConfig
    from nautilus_trader.config import TradingNodeConfig
    from nautilus_trader.live.node import TradingNode
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.identifiers import TraderId

    # Get environment
    env = settings.bybit_environment.lower()
    if env == "demo":
        environment = BybitEnvironment.DEMO
    elif env == "testnet":
        environment = BybitEnvironment.TESTNET
    else:
        environment = BybitEnvironment.MAINNET

    # Create instrument ID
    symbol_with_spot = f"{symbol}-SPOT"
    instrument_id = InstrumentId.from_str(f"{symbol_with_spot}.{BYBIT}")
    bar_type = BarType.from_str(f"{instrument_id}-{INTERVAL_MAP[interval]}-LAST-EXTERNAL")

    # Create config
    config = TradingNodeConfig(
        trader_id=TraderId("HISTORICAL-LOADER-001"),
        logging=LoggingConfig(
            log_level="INFO",
            use_pyo3=True,
        ),
        data_clients={
            BYBIT: BybitDataClientConfig(
                environment=environment,
                instrument_provider=InstrumentProviderConfig(load_all=True),
                product_types=(BybitProductType.SPOT,),
            ),
        },
        timeout_connection=30.0,
        timeout_reconciliation=10.0,
        timeout_portfolio=10.0,
        timeout_disconnection=10.0,
        timeout_post_stop=1.0,
    )

    # Create node
    node = TradingNode(config=config)

    # Collected bars
    collected_bars = []

    # Create data handler
    from nautilus_trader.trader.actor import Actor

    class HistoricalDataHandler(Actor):
        def __init__(self):
            super().__init__()

        def on_start(self):
            logger.info("historical_handler_started", symbol=symbol, interval=interval)
            self.subscribe_bars(bar_type)

        def on_bar(self, bar: Bar):
            # Filter by date range
            bar_time = datetime.fromtimestamp(bar.ts_event / 1e9, tz=UTC)
            if start_date <= bar_time <= end_date:
                collected_bars.append(bar)
                if len(collected_bars) % 100 == 0:
                    logger.info("bars_collected", count=len(collected_bars))

        def on_stop(self):
            logger.info("historical_handler_stopped", total_bars=len(collected_bars))

    # Add handler
    handler = HistoricalDataHandler()
    node.trader.add_actor(handler)

    # Register client factory
    node.add_data_client_factory(BYBIT, BybitLiveDataClientFactory)
    node.build()

    # Connect and run
    logger.info("connecting_to_bybit", symbol=symbol, interval=interval)
    node.connect()

    # Wait for data collection (simplified - in production would use proper synchronization)
    await asyncio.sleep(10)

    # Disconnect
    node.disconnect()
    node.dispose()

    return collected_bars


async def main():
    args = parse_args()

    # Calculate date range
    end_date = datetime.now(UTC)
    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=UTC)

    start_date = end_date - timedelta(days=args.days)
    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=UTC)

    logger.info(
        "loading_config",
        symbols=args.symbol,
        interval=args.interval,
        start=start_date.isoformat(),
        end=end_date.isoformat(),
    )

    total_loaded = 0

    for symbol in args.symbol:
        logger.info("loading_symbol", symbol=symbol)

        try:
            # Load bars via NautilusTrader
            bars = await load_bars_via_nautilus(
                symbol=symbol,
                interval=args.interval,
                start_date=start_date,
                end_date=end_date,
            )

            if bars:
                # Store to PostgreSQL
                inserted = store_bars_to_postgres(bars, symbol, args.interval)
                total_loaded += inserted
                logger.info(
                    "symbol_completed",
                    symbol=symbol,
                    bars_received=len(bars),
                    bars_inserted=inserted,
                )
            else:
                logger.warning("no_bars_received", symbol=symbol)

        except Exception as e:
            logger.error("symbol_error", symbol=symbol, error=str(e))

    logger.info("loading_completed", total_loaded=total_loaded)


if __name__ == "__main__":
    asyncio.run(main())
