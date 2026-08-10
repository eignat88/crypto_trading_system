"""
Bybit Market Data Collector using NautilusTrader.

This module collects market data from Bybit via NautilusTrader
and stores it in PostgreSQL.
"""

import signal

import structlog
from nautilus_trader.adapters.bybit import (
    BYBIT,
    BybitDataClientConfig,
    BybitEnvironment,
    BybitLiveDataClientFactory,
    BybitProductType,
)
from nautilus_trader.config import InstrumentProviderConfig, LoggingConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.identifiers import InstrumentId, TraderId

from app.config.settings import settings

logger = structlog.get_logger()

# Global flag for graceful shutdown
_running = True


def _signal_handler(sig, frame):
    global _running
    logger.info("shutdown_signal_received", signal=sig)
    _running = False


class BybitMarketDataCollector:
    """
    Collects market data from Bybit using NautilusTrader.

    This collector:
    1. Connects to Bybit
    2. Loads Spot instruments (BTCUSDT, ETHUSDT)
    3. Subscribes to 1-minute bars
    4. Saves data to PostgreSQL
    """

    def __init__(self):
        self.node: TradingNode | None = None
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

    def _get_bybit_environment(self) -> BybitEnvironment:
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

    def _get_product_type(self) -> BybitProductType:
        """Get product type (always SPOT for this project)."""
        return BybitProductType.SPOT

    def _get_instrument_ids(self) -> list[InstrumentId]:
        """Get instrument IDs from settings."""
        product_type = self._get_product_type()
        symbols = [s.strip() for s in settings.trading_symbols.split(",")]

        instrument_ids = []
        for symbol in symbols:
            # Ensure -SPOT suffix
            if not symbol.endswith("-SPOT"):
                symbol = f"{symbol}-SPOT"
            instrument_ids.append(InstrumentId.from_str(f"{symbol}.{BYBIT}"))

        return instrument_ids

    def _get_bar_types(self) -> list[BarType]:
        """Get bar types for subscription."""
        instrument_ids = self._get_instrument_ids()
        bar_types = []

        for instrument_id in instrument_ids:
            # 1-minute bars
            bar_type = BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")
            bar_types.append(bar_type)

        return bar_types

    def _create_config(self) -> TradingNodeConfig:
        """Create trading node configuration."""
        environment = self._get_bybit_environment()
        product_type = self._get_product_type()

        config = TradingNodeConfig(
            trader_id=TraderId("CRYPTO-TRADER-001"),
            logging=LoggingConfig(
                log_level=settings.log_level,
                use_pyo3=True,
            ),
            data_clients={
                BYBIT: BybitDataClientConfig(
                    environment=environment,
                    instrument_provider=InstrumentProviderConfig(load_all=True),
                    product_types=(product_type,),
                ),
            },
            timeout_connection=20.0,
            timeout_reconciliation=10.0,
            timeout_portfolio=10.0,
            timeout_disconnection=10.0,
            timeout_post_stop=1.0,
        )

        return config

    def _create_data_handler(self):
        """Create a data handler actor."""
        from nautilus_trader.trader.actor import Actor

        instrument_ids = self._get_instrument_ids()
        bar_types = self._get_bar_types()

        # Create a simple actor to handle data
        class DataHandler(Actor):
            def __init__(self):
                super().__init__()

            def on_start(self):
                logger.info("data_handler_started")
                # Subscribe to bars
                for bar_type in bar_types:
                    self.subscribe_bars(bar_type)
                    logger.info("subscribed_to_bars", bar_type=str(bar_type))

            def on_bar(self, bar: Bar):
                logger.info(
                    "bar_received",
                    bar_type=str(bar.bar_type),
                    open=str(bar.open),
                    high=str(bar.high),
                    low=str(bar.low),
                    close=str(bar.close),
                    volume=str(bar.volume),
                    ts_event=bar.ts_event,
                )
                # TODO: Save to PostgreSQL

            def on_stop(self):
                logger.info("data_handler_stopped")

        return DataHandler()

    async def start(self):
        """Start the collector."""
        global _running

        logger.info(
            "collector_starting",
            environment=settings.bybit_environment,
            symbols=settings.trading_symbols,
        )

        try:
            # Create config
            config = self._create_config()

            # Create node
            self.node = TradingNode(config=config)

            # Create and add data handler
            handler = self._create_data_handler()
            self.node.trader.add_actor(handler)

            # Register client factories
            self.node.add_data_client_factory(BYBIT, BybitLiveDataClientFactory)
            self.node.build()

            logger.info("node_built", trader_id=str(config.trader_id))

            # Run node (this blocks)
            self.node.run()

        except KeyboardInterrupt:
            logger.info("interrupted_by_user")
        except Exception as e:
            logger.error("collector_error", error=str(e))
            raise
        finally:
            if self.node:
                self.node.dispose()
            logger.info("collector_stopped")


async def run_collector():
    """Run the market data collector."""
    collector = BybitMarketDataCollector()
    await collector.start()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_collector())
