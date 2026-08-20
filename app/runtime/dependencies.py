from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy import create_engine

from app.config.settings import Settings
from app.database.paper_state_repository_pg import PaperStateRepositoryPostgres
from app.exchange.paper_execution_engine import ExecutionRequest, PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.exchange.paper_state_repository import PaperStateRepository
from app.execution.paper_trading_runtime import PaperTradingRuntime
from app.monitoring.heartbeat import Heartbeat, PostgresHeartbeatRepository
from app.monitoring.notifier import ConsoleNotifier, Notifier
from app.risk.persistence import PostgresRiskStateStore
from app.risk.risk_engine import RiskConfig, RiskEngine


class RiskEngineAdapter:
    """The sole bridge from runtime requests to the project's RiskEngine."""

    def __init__(self, engine: RiskEngine, total_capital: Decimal) -> None:
        self.engine = engine
        self.total_capital = total_capital

    async def validate_request(
        self, request: ExecutionRequest, execution: PaperExecutionEngine
    ) -> bool:
        price = execution.last_candle.close if execution.last_candle else Decimal("0")
        positions = {
            symbol: {
                "symbol": symbol,
                "value": position.quantity * position.average_price,
                "side": "buy",
            }
            for symbol, position in execution.positions.items()
        }
        result = self.engine.check_trade(
            symbol=request.symbol,
            side=request.side.value,
            quantity=request.quantity,
            price=price,
            current_balance=execution.cash_balance,
            current_positions=positions,
            total_capital=self.total_capital,
        )
        return result.approved


@dataclass
class PaperDependencies:
    runtime: PaperTradingRuntime
    repository: PaperStateRepository
    risk_engine: RiskEngine
    database_check: Callable[[], Awaitable[bool]]
    migration_check: Callable[[], Awaitable[bool]]
    warmup: Callable[[list[str], int], Awaitable[dict[str, int]]]
    close: Callable[[], Awaitable[None]]
    trading_mode: str
    exchange: str
    symbols: list[str]
    initial_capital: Decimal
    risk_config: RiskConfig
    warmup_candles: int = 200
    pnl_checkpoint: Callable[[], Awaitable[None]] | None = None
    metadata: dict[str, Any] | None = None
    heartbeat: Heartbeat | None = None
    notifier: Notifier | None = None


async def build_paper_dependencies(settings: Settings) -> PaperDependencies:
    """Build production adapters once; no second runtime or risk controller is created."""
    connection = await asyncpg.connect(settings.database_url_sync)
    monitoring_pool = await asyncpg.create_pool(
        settings.database_url_sync,
        min_size=1,
        max_size=2,
    )
    repository = PaperStateRepositoryPostgres(connection)
    sync_engine = create_engine(settings.database_url_sync)
    risk_config = RiskConfig(
        max_risk_per_trade=Decimal(str(settings.max_risk_per_trade)),
        max_position_size=Decimal(str(settings.max_position_size)),
        max_asset_exposure=Decimal(str(settings.max_asset_exposure)),
        max_capital_utilization=Decimal(str(settings.max_capital_utilization)),
        daily_loss_limit=Decimal(str(settings.daily_loss_limit)),
        weekly_loss_limit=Decimal(str(settings.weekly_loss_limit)),
        max_drawdown=Decimal(str(settings.max_drawdown)),
    )
    risk_engine = RiskEngine(risk_config, PostgresRiskStateStore(sync_engine))
    capital = Decimal(str(settings.paper_initial_balance))
    execution = PaperExecutionEngine(state_repository=repository)
    execution.cash_balance = capital
    heartbeat = Heartbeat("paper-runtime-001", PostgresHeartbeatRepository(monitoring_pool))
    runtime = PaperTradingRuntime(
        market_data=PaperMarketData([]),
        execution_engine=execution,
        risk_manager=RiskEngineAdapter(risk_engine, capital),
        state_repository=repository,
        heartbeat=heartbeat,
    )

    async def database_check() -> bool:
        return bool(await connection.fetchval("SELECT 1"))

    async def migration_check() -> bool:
        return bool(
            await connection.fetchval(
                """SELECT to_regclass('public.schema_migrations') IS NOT NULL
                          AND to_regclass('monitoring.runtime_health') IS NOT NULL
                          AND EXISTS (
                              SELECT 1 FROM public.schema_migrations WHERE version = 50
                          )"""
            )
        )

    async def warmup(symbols: list[str], required: int) -> dict[str, int]:
        rows = await connection.fetch(
            """SELECT i.symbol, count(*) AS candle_count
               FROM (SELECT c.instrument_id, c.open_time,
                            row_number() OVER (
                                PARTITION BY c.instrument_id ORDER BY c.open_time DESC
                            ) AS rn
                     FROM dds.candle c
                     WHERE c.interval_code = '1h' AND c.is_valid = true
                           AND c.close_time <= now()) recent
               JOIN dds.instrument i ON i.instrument_id = recent.instrument_id
               WHERE recent.rn <= $1 AND i.symbol = ANY($2::text[])
               GROUP BY i.symbol""",
            required,
            symbols,
        )
        return {str(row["symbol"]): int(row["candle_count"]) for row in rows}

    async def close() -> None:
        await monitoring_pool.close()
        await connection.close()
        sync_engine.dispose()

    async def pnl_checkpoint() -> None:
        snapshots = await repository.load_pnl_snapshots()
        if snapshots:
            await repository.save_pnl_snapshot(snapshots[-1])

    return PaperDependencies(
        runtime=runtime,
        repository=repository,
        risk_engine=risk_engine,
        database_check=database_check,
        migration_check=migration_check,
        warmup=warmup,
        close=close,
        trading_mode=settings.trading_mode.value,
        exchange=settings.bybit_environment,
        symbols=[value.strip() for value in settings.trading_symbols.split(",") if value.strip()],
        initial_capital=capital,
        risk_config=risk_config,
        pnl_checkpoint=pnl_checkpoint,
        heartbeat=heartbeat,
        notifier=ConsoleNotifier(),
    )
