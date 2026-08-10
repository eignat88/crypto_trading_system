"""Integration test for Bybit connection."""

import asyncio

import pytest

from app.config.settings import settings


@pytest.mark.integration
class TestBybitConnection:
    """Integration tests for Bybit connection.

    These tests require network access to Bybit API.
    """

    @pytest.mark.asyncio
    async def test_bybit_connection(self):
        """Test that we can connect to Bybit."""
        from nautilus_trader.adapters.bybit import BYBIT
        from nautilus_trader.adapters.bybit import BybitDataClientConfig
        from nautilus_trader.adapters.bybit import BybitEnvironment
        from nautilus_trader.adapters.bybit import BybitLiveDataClientFactory
        from nautilus_trader.adapters.bybit import BybitProductType
        from nautilus_trader.config import InstrumentProviderConfig
        from nautilus_trader.config import LoggingConfig
        from nautilus_trader.config import TradingNodeConfig
        from nautilus_trader.live.node import TradingNode
        from nautilus_trader.model.identifiers import TraderId

        # Get environment
        env = settings.bybit_environment.lower()
        if env == "demo":
            environment = BybitEnvironment.DEMO
        elif env == "testnet":
            environment = BybitEnvironment.TESTNET
        else:
            environment = BybitEnvironment.MAINNET

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

        # Connect
        node.connect()

        # Wait for connection
        await asyncio.sleep(5)

        # Check connection
        assert node.data_client is not None
        assert node.data_client.is_connected

        # Disconnect
        node.disconnect()
        node.dispose()

    @pytest.mark.asyncio
    async def test_spot_instruments_loaded(self):
        """Test that Spot instruments are loaded."""
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

        # Get environment
        env = settings.bybit_environment.lower()
        if env == "demo":
            environment = BybitEnvironment.DEMO
        elif env == "testnet":
            environment = BybitEnvironment.TESTNET
        else:
            environment = BybitEnvironment.MAINNET

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

        # Connect
        node.connect()

        # Wait for instruments to load
        await asyncio.sleep(5)

        # Check instruments
        instruments = node.instrument_provider.get_all()

        # Check for BTCUSDT-SPOT
        btcusdt = InstrumentId.from_str(f"BTCUSDT-SPOT.{BYBIT}")
        assert btcusdt in instruments, f"BTCUSDT-SPOT not found in {list(instruments.keys())}"

        # Check for ETHUSDT-SPOT
        ethusdt = InstrumentId.from_str(f"ETHUSDT-SPOT.{BYBIT}")
        assert ethusdt in instruments, f"ETHUSDT-SPOT not found in {list(instruments.keys())}"

        # Disconnect
        node.disconnect()
        node.dispose()
