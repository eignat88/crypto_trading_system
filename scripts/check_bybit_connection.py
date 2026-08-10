from nautilus_trader.adapters.bybit import (
    BybitDataClientConfig,
    BybitDataClientFactory,
    BybitEnvironment,
    BybitProductType,
)
from nautilus_trader.common import Environment
from nautilus_trader.live import LiveNode
from nautilus_trader.model import TraderId

from app.config.settings import settings


def get_bybit_environment() -> BybitEnvironment:
    env = settings.bybit_environment.lower()

    if env == "demo":
        return BybitEnvironment.DEMO
    if env == "testnet":
        return BybitEnvironment.TESTNET
    if env == "mainnet":
        return BybitEnvironment.MAINNET

    raise ValueError(f"Unknown BYBIT_ENVIRONMENT: {env}")


def main() -> int:
    print("=" * 60)
    print("Bybit Data Connection Test")
    print("=" * 60)

    print(f"Trading mode: {settings.trading_mode}")
    print(f"Bybit environment: {settings.bybit_environment}")
    print(f"Symbols: {settings.trading_symbols}")
    print()

    config = BybitDataClientConfig(
        product_types=(BybitProductType.SPOT,),
        environment=get_bybit_environment(),
    )

    print("BybitDataClientConfig: OK")

    node = (
        LiveNode.builder(
            "BYBIT-DATA-CHECK",
            TraderId("TEST-001"),
            Environment.LIVE,
        )
        .add_data_client(
            None,
            BybitDataClientFactory(),
            config,
        )
        .build()
    )

    print("LiveNode build: OK")
    print("Execution client configured: NO")
    print("Trading orders possible from this script: NO")
    print()

    try:
        print("Starting Bybit data client...")
        node.start()
        print("LiveNode start: OK")
        print(f"Node running: {node.is_running}")
    finally:
        print("Stopping node...")
        node.stop()
        node.dispose()

    print()
    print("Bybit data connection test: PASSED")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
