from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.execution.paper_trading_runtime import PaperTradingRuntime
from app.risk.risk_engine import RiskConfig, RiskEngine
from app.runtime.dependencies import PaperDependencies
from app.runtime.lifecycle import RuntimeState
from app.runtime.paper_application import PaperApplication

pytestmark = pytest.mark.asyncio


class Repository:
    saved = 0

    async def load_state(self):
        return None

    async def load_positions(self):
        return []

    async def save_state(self, state):
        self.saved += 1

    async def save_pnl_snapshot(self, snapshot):
        pass

    async def load_pnl_snapshots(self):
        return []


def dependencies(repository: Repository, available: int = 200) -> PaperDependencies:
    async def yes():
        return True

    async def warmup(symbols, required):
        return {symbols[0]: available}

    async def close():
        pass

    risk = RiskEngine(RiskConfig())
    engine = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    runtime = PaperTradingRuntime(PaperMarketData([]), engine, state_repository=repository)  # type: ignore[arg-type]
    return PaperDependencies(
        runtime,
        repository,
        risk,
        yes,
        yes,
        warmup,
        close,
        "paper",
        "demo",
        ["BTCUSDT"],
        Decimal("1000"),
        risk.config,
    )  # type: ignore[arg-type]


async def test_application_runs_preflight_restore_and_warmup() -> None:
    app = PaperApplication(dependencies(Repository()))
    await app.start()
    assert app.lifecycle.state is RuntimeState.RUNNING
    assert app.trading_enabled
    await app.stop()
    assert app.lifecycle.state is RuntimeState.STOPPED


async def test_insufficient_warmup_disables_orders_but_starts_runtime() -> None:
    app = PaperApplication(dependencies(Repository(), available=50))
    await app.start()
    assert app.lifecycle.state is RuntimeState.RUNNING
    assert not app.trading_enabled
    await app.stop()


async def test_unknown_mode_never_starts_execution() -> None:
    deps = dependencies(Repository())
    deps.trading_mode = "test"
    app = PaperApplication(deps)
    with pytest.raises(RuntimeError, match="Unknown trading mode"):
        await app.start()
    assert app.lifecycle.state is RuntimeState.STOPPED
