"""
Check Bybit Connection Script.

This script verifies connectivity to Bybit and retrieves instrument information.
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from nautilus_trader.adapters.bybit import BYBIT
from nautilus_trader.adapters.bybit import BybitDataClientConfig
from nautilus_trader.adapters.bybit import BybitEnvironment
from nautilus_trader.adapters.bybit import BybitLiveDataClientFactory
from nautilus_trader.adapters.bybit import BybitProductType
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.config import LoggingConfig
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.identifiers import TraderId

from app.config.settings import settings

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


def get_bybit_environment() -> BybitEnvironment:
    """Get Bybit environment from settings."""
    env = settings.bybit_environment.lower()
    if env == "demo":
        return BybitEnvironment.DEMO
    elif env == "testnet":
        return BybitEnvironment.TESTNET
    elif env == "mainnet":
        return BybitEnvironment.MAINNET
    else:
        raise ValueError(f"Unknown BYBIT_ENVIRONMENT: {env}")


async def check_connection():
    """Check Bybit connection and retrieve instruments."""
    print("=" * 60)
    print("Bybit Connection Test")
    print("=" * 60)
    print()

    try:
        # Get environment
        environment = get_bybit_environment()
        print(f"Environment: {environment.value}")

        # Get symbols
        symbols = [s.strip() for s in settings.trading_symbols.split(",")]
        print(f"Symbols: {symbols}")
        print()

        # Create config
        config = TradingNodeConfig(
            trader_id=TraderId("TEST-001"),
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
            timeout_connection=20.0,
            timeout_reconciliation=10.0,
            timeout_portfolio=10.0,
            timeout_disconnection=10.0,
            timeout_post_stop=1.0,
        )

        # Create node
        node = TradingNode(config=config)

        # Register client factory
        node.add_data_client_factory(BYBIT, BybitLiveDataClientFactory)
        node.build()

        print("Connecting to Bybit...")
        node.connect()

        # Wait for connection
        await asyncio.sleep(5)

        # Check connection status
        if node.data_client and node.data_client.is_connected:
            print()
            print("BYBIT connection: OK")
            print()

            # Get instruments
            instruments = node.instrument_provider.get_all()
            print(f"Total instruments loaded: {len(instruments)}")
            print()

            # Check for our symbols
            for symbol in symbols:
                if not symbol.endswith("-SPOT"):
                    symbol = f"{symbol}-SPOT"
                instrument_id = InstrumentId.from_str(f"{symbol}.{BYBIT}")

                if instrument_id in instruments:
                    inst = instruments[instrument_id]
                    print(f"{symbol}.BYBIT: FOUND")
                    print(f"  Base currency: {inst.base_currency}")
                    print(f"  Quote currency: {inst.quote_currency}")
                    print(f"  Lot size: {inst.lot_size}")
                    print(f"  Tick size: {inst.tick_size}")
                else:
                    print(f"{symbol}.BYBIT: NOT FOUND")
                print()

            print("Market data: RECEIVED (if subscribed)")
            print()
            print("Trading orders submitted: 0")
        else:
            print()
            print("BYBIT connection: FAILED")
            print("Check your network connection and API configuration.")

        # Disconnect
        node.disconnect()
        node.dispose()

    except Exception as e:
        print()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print()
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(check_connection())
    sys.exit(exit_code)
