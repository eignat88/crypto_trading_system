"""Integration test for Bybit connection."""

import asyncio
import os

import pytest

from app.config.settings import settings

BYBIT_INTEGRATION_ENABLED = bool(
    os.getenv("BYBIT_API_KEY")
    and os.getenv("BYBIT_API_SECRET")
)


pytestmark = pytest.mark.skipif(
    not BYBIT_INTEGRATION_ENABLED,
    reason="Bybit live integration disabled: credentials are not configured",
)


@pytest.mark.integration
class TestBybitConnection:
    """Integration tests for Bybit connection.

    These tests require network access to Bybit API and credentials.
    """

    @pytest.mark.asyncio
    async def test_bybit_connection(self):
        """Test that we can connect to Bybit."""
        from nautilus_trader.adapters.bybit import (
            BYBIT,
            BybitDataClientConfig,
            BybitDataClientFactory,
            BybitEnvironment,
            BybitProductType,
        )
        from nautilus_trader.config import (
            InstrumentProviderConfig,
            LoggingConfig,
            TradingNodeConfig,
        )
        from nautilus_trader.live.node import TradingNode
        from nautilus_trader.model.identifiers import TraderId

        environment = self._environment(BybitEnvironment)
        config = self._config(
            BYBIT,
            BybitDataClientConfig,
            BybitProductType,
            InstrumentProviderConfig,
            LoggingConfig,
            TradingNodeConfig,
            TraderId,
            environment,
        )

        node = TradingNode(config=config)
        node.add_data_client_factory(BYBIT, BybitDataClientFactory)
        node.build()
        node.connect()

        await asyncio.sleep(5)

        assert node.data_client is not None
        assert node.data_client.is_connected

        node.disconnect()
        node.dispose()

    @pytest.mark.asyncio
    async def test_spot_instruments_loaded(self):
        """Test that Spot instruments are loaded."""
        from nautilus_trader.adapters.bybit import (
            BYBIT,
            BybitDataClientConfig,
            BybitDataClientFactory,
            BybitEnvironment,
            BybitProductType,
        )
        from nautilus_trader.config import (
            InstrumentProviderConfig,
            LoggingConfig,
            TradingNodeConfig,
        )
        from nautilus_trader.live.node import TradingNode
        from nautilus_trader.model.identifiers import InstrumentId, TraderId

        environment = self._environment(BybitEnvironment)
        config = self._config(
            BYBIT,
            BybitDataClientConfig,
            BybitProductType,
            InstrumentProviderConfig,
            LoggingConfig,
            TradingNodeConfig,
            TraderId,
            environment,
        )

        node = TradingNode(config=config)
        node.add_data_client_factory(BYBIT, BybitDataClientFactory)
        node.build()
        node.connect()

        await asyncio.sleep(5)

        instruments = node.instrument_provider.get_all()

        assert InstrumentId.from_str(f"BTCUSDT-SPOT.{BYBIT}") in instruments
        assert InstrumentId.from_str(f"ETHUSDT-SPOT.{BYBIT}") in instruments

        node.disconnect()
        node.dispose()

    @staticmethod
    def _environment(BybitEnvironment):
        env = settings.bybit_environment.lower()
        if env == "demo":
            return BybitEnvironment.DEMO
        if env == "testnet":
            return BybitEnvironment.TESTNET
        return BybitEnvironment.MAINNET

    @staticmethod
    def _config(
        BYBIT,
        BybitDataClientConfig,
        BybitProductType,
        InstrumentProviderConfig,
        LoggingConfig,
        TradingNodeConfig,
        TraderId,
        environment,
    ):
        return TradingNodeConfig(
            trader_id=TraderId("TEST-001"),
            logging=LoggingConfig(log_level="INFO", use_pyo3=True),
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
