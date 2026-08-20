from decimal import Decimal

import pytest

from app.runtime.preflight import StartupPreflight

pytestmark = pytest.mark.asyncio


class Repository:
    async def load_state(self):
        return None


def preflight(mode: str = "paper", database: bool = True) -> StartupPreflight:
    async def check_database() -> bool:
        return database

    async def check_migrations() -> bool:
        return True

    return StartupPreflight(
        trading_mode=mode,
        exchange="demo",
        symbols=["BTCUSDT"],
        initial_capital=Decimal("1000"),
        risk_config=object(),
        database_check=check_database,
        migration_check=check_migrations,
        repository=Repository(),
    )


@pytest.mark.parametrize("mode", ["test", "live"])
async def test_non_paper_mode_fails_closed(mode: str) -> None:
    result = await preflight(mode).run()
    assert not result.success
    assert any(mode.capitalize() in error or mode in error for error in result.errors)


async def test_database_unavailable_blocks_startup() -> None:
    result = await preflight(database=False).run()
    assert not result.success
    assert "Database unavailable" in result.errors
