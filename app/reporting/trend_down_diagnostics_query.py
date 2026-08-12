from __future__ import annotations

import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backtest.commission_model import CommissionConfig
from app.database.connection import async_session_factory
from app.reporting.trend_down_diagnostics import (
    _decimal,
    reconstruct_trend_down_exits,
    summarize_trend_down_diagnostics,
)


async def build_trend_down_diagnostics(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
):
    """Build read-only TREND_DOWN diagnostics with explicit datetime query bounds.

    The candle upper bound is calculated in Python instead of using
    ``:period_end + interval`` in SQL. This avoids asyncpg/PostgreSQL bind-type
    inference turning the comparison into ``timestamptz < interval``.
    """
    async with session_factory() as session:
        run_result = await session.execute(
            text(
                """
                SELECT run_id, exchange_name, symbol, interval_code,
                       period_start, period_end, backtest_config
                FROM mart.backtest_run
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        run = run_result.mappings().one_or_none()
        if run is None:
            raise ValueError(f"Backtest run not found: {run_id}")
        if str(run["interval_code"]) != "1h":
            raise ValueError(
                "TREND_DOWN diagnostics currently supports only 1h baseline runs"
            )

        fill_result = await session.execute(
            text(
                """
                SELECT f.sequence_no, f.side, f.quantity, f.price, f.commission,
                       f.fill_time, o.payload -> 'signal' AS signal
                FROM mart.backtest_fill f
                JOIN mart.backtest_order o
                  ON o.run_id = f.run_id
                 AND o.order_id = f.order_id
                WHERE f.run_id = :run_id
                ORDER BY f.sequence_no
                """
            ),
            {"run_id": run_id},
        )
        fill_rows = [dict(row) for row in fill_result.mappings().all()]

        candle_end = run["period_end"] + timedelta(hours=4)
        candle_result = await session.execute(
            text(
                """
                SELECT c.open_time, c.close_price, c.low_price, c.high_price,
                       mr.regime
                FROM dds.candle c
                JOIN dds.instrument i ON i.instrument_id = c.instrument_id
                LEFT JOIN dds.market_regime mr ON mr.candle_id = c.candle_id
                WHERE i.exchange_name = :exchange_name
                  AND i.symbol = :symbol
                  AND c.interval_code = :interval_code
                  AND c.open_time >= :period_start
                  AND c.open_time < :candle_end
                  AND c.is_valid = true
                ORDER BY c.open_time
                """
            ),
            {
                "exchange_name": run["exchange_name"],
                "symbol": run["symbol"],
                "interval_code": run["interval_code"],
                "period_start": run["period_start"],
                "candle_end": candle_end,
            },
        )
        candle_rows = [dict(row) for row in candle_result.mappings().all()]

    config = run["backtest_config"] or {}
    if isinstance(config, str):
        config = json.loads(config)
    commission = config.get("commission", {})
    commission_config = CommissionConfig(
        maker_fee=_decimal(commission.get("maker_fee", "0.001")),
        taker_fee=_decimal(commission.get("taker_fee", "0.001")),
        minimum_fee=_decimal(commission.get("minimum_fee", "0.0001")),
    )

    records = reconstruct_trend_down_exits(
        run_id=run_id,
        symbol=str(run["symbol"]),
        fill_rows=fill_rows,
        candle_rows=candle_rows,
        commission_config=commission_config,
        bar_delta=timedelta(hours=1),
    )
    return summarize_trend_down_diagnostics(
        run_id=run_id,
        symbol=str(run["symbol"]),
        interval=str(run["interval_code"]),
        records=records,
    )
