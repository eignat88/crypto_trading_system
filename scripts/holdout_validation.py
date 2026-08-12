from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database.connection import async_session_factory
from app.reporting.holdout_validation import (
    HoldoutDefinition,
    SymbolDataHealth,
    completed_interval_end,
    evaluate_open_gate,
    expected_completed_candles,
    holdout_from_dict,
)

DEFAULT_DEFINITION = Path("config/validation/breakout_retest_v2_holdout.json")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _load_definition(path: Path) -> HoldoutDefinition:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return holdout_from_dict(payload)


def _strategy_implemented(definition: HoldoutDefinition) -> bool:
    module_name = f"app.strategies.{definition.parameters_version}"
    return importlib.util.find_spec(module_name) is not None


async def _symbol_health(
    definition: HoldoutDefinition,
    symbol: str,
    *,
    as_of: datetime,
) -> SymbolDataHealth:
    end = completed_interval_end(definition, now=as_of)
    expected = expected_completed_candles(definition, now=as_of)
    if expected == 0:
        return SymbolDataHealth(symbol, 0, 0, 0, 0, 0, 0, 0)

    params = {
        "exchange": definition.exchange,
        "symbol": symbol,
        "interval": definition.interval,
        "start": definition.period_start,
        "end": end,
        "indicator_model_version": definition.indicator_model_version,
        "regime_model_version": definition.regime_model_version,
    }

    candle_sql = text(
        """
        SELECT c.open_time, c.is_valid
        FROM dds.candle c
        JOIN dds.instrument i ON i.instrument_id = c.instrument_id
        WHERE i.exchange_name = :exchange
          AND i.symbol = :symbol
          AND c.interval_code = :interval
          AND c.open_time >= :start
          AND c.open_time < :end
        ORDER BY c.open_time
        """
    )
    indicator_sql = text(
        """
        SELECT COUNT(*)
        FROM dds.candle c
        JOIN dds.instrument i ON i.instrument_id = c.instrument_id
        WHERE i.exchange_name = :exchange
          AND i.symbol = :symbol
          AND c.interval_code = :interval
          AND c.open_time >= :start
          AND c.open_time < :end
          AND c.is_valid = true
          AND EXISTS (
              SELECT 1 FROM dds.indicator x
              WHERE x.candle_id = c.candle_id
                AND x.model_version = :indicator_model_version
                AND x.indicator_name = 'EMA'
                AND x.indicator_params = '{"period": 20}'::jsonb
          )
          AND EXISTS (
              SELECT 1 FROM dds.indicator x
              WHERE x.candle_id = c.candle_id
                AND x.model_version = :indicator_model_version
                AND x.indicator_name = 'EMA'
                AND x.indicator_params = '{"period": 50}'::jsonb
          )
          AND EXISTS (
              SELECT 1 FROM dds.indicator x
              WHERE x.candle_id = c.candle_id
                AND x.model_version = :indicator_model_version
                AND x.indicator_name = 'EMA'
                AND x.indicator_params = '{"period": 200}'::jsonb
          )
          AND EXISTS (
              SELECT 1 FROM dds.indicator x
              WHERE x.candle_id = c.candle_id
                AND x.model_version = :indicator_model_version
                AND x.indicator_name = 'RSI'
                AND x.indicator_params = '{"period": 14}'::jsonb
          )
          AND EXISTS (
              SELECT 1 FROM dds.indicator x
              WHERE x.candle_id = c.candle_id
                AND x.model_version = :indicator_model_version
                AND x.indicator_name = 'ATR'
                AND x.indicator_params = '{"period": 14}'::jsonb
          )
          AND EXISTS (
              SELECT 1 FROM dds.indicator x
              WHERE x.candle_id = c.candle_id
                AND x.model_version = :indicator_model_version
                AND x.indicator_name = 'VOLATILITY'
                AND x.indicator_params = '{"period": 20}'::jsonb
          )
        """
    )
    regime_sql = text(
        """
        SELECT COUNT(*)
        FROM dds.candle c
        JOIN dds.instrument i ON i.instrument_id = c.instrument_id
        WHERE i.exchange_name = :exchange
          AND i.symbol = :symbol
          AND c.interval_code = :interval
          AND c.open_time >= :start
          AND c.open_time < :end
          AND c.is_valid = true
          AND EXISTS (
              SELECT 1 FROM dds.market_regime mr
              WHERE mr.candle_id = c.candle_id
                AND mr.indicator_model_version = :indicator_model_version
                AND mr.regime_model_version = :regime_model_version
          )
        """
    )

    async with async_session_factory() as session:
        rows = (await session.execute(candle_sql, params)).all()
        indicator_complete = int((await session.execute(indicator_sql, params)).scalar_one())
        regime_complete = int((await session.execute(regime_sql, params)).scalar_one())

    times = [row.open_time for row in rows]
    unique_times = set(times)
    duplicate_intervals = len(times) - len(unique_times)
    invalid_candles = sum(1 for row in rows if not bool(row.is_valid))

    expected_times = {
        definition.period_start + timedelta(hours=offset)
        for offset in range(expected)
    }
    missing_intervals = len(expected_times - unique_times)

    return SymbolDataHealth(
        symbol=symbol,
        expected_candles=expected,
        candle_count=len(times),
        missing_intervals=missing_intervals,
        duplicate_intervals=duplicate_intervals,
        invalid_candles=invalid_candles,
        indicator_complete_candles=indicator_complete,
        regime_complete_candles=regime_complete,
    )


async def _data_health(definition: HoldoutDefinition, as_of: datetime) -> int:
    print("INDEPENDENT HOLDOUT DATA HEALTH")
    print("===============================")
    print(f"validation_id        : {definition.validation_id}")
    print(f"period               : {definition.period_start.isoformat()} -> {definition.period_end.isoformat()}")
    print(f"as_of                : {as_of.astimezone(timezone.utc).isoformat()}")
    print(f"completed_through    : {completed_interval_end(definition, now=as_of).isoformat()}")
    print("performance_access   : SEALED")
    print("performance_metrics  : NOT_COMPUTED")

    healthy = True
    for symbol in definition.symbols:
        health = await _symbol_health(definition, symbol, as_of=as_of)
        healthy = healthy and health.healthy
        print()
        print(symbol)
        print(f"  expected_candles   : {health.expected_candles}")
        print(f"  stored_candles     : {health.candle_count}")
        print(f"  missing_intervals  : {health.missing_intervals}")
        print(f"  duplicate_intervals: {health.duplicate_intervals}")
        print(f"  invalid_candles    : {health.invalid_candles}")
        print(f"  indicator_complete : {health.indicator_complete_candles}")
        print(f"  regime_complete    : {health.regime_complete_candles}")
        print(f"  status             : {'PASS' if health.healthy else 'INCOMPLETE'}")

    print()
    print(f"data_health          : {'PASS' if healthy else 'INCOMPLETE'}")
    return 0 if healthy else 2


async def main() -> None:
    parser = argparse.ArgumentParser(description="Sealed independent holdout validation gate")
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("health", help="Data-health only; never executes the strategy")
    health.add_argument("--as-of", type=str, default=None)
    subparsers.add_parser("open-check", help="Check whether performance access may be opened")

    args = parser.parse_args()
    definition = _load_definition(args.definition)

    if args.command == "health":
        as_of = _now_utc() if args.as_of is None else datetime.fromisoformat(args.as_of)
        raise SystemExit(await _data_health(definition, as_of))

    gate = evaluate_open_gate(
        definition,
        now=_now_utc(),
        strategy_implemented=_strategy_implemented(definition),
    )
    print("INDEPENDENT HOLDOUT OPEN GATE")
    print("=============================")
    print(f"validation_id        : {definition.validation_id}")
    print(f"unlock_at            : {definition.unlock_at.isoformat()}")
    print(f"strategy_version     : {definition.parameters_version}")
    print(f"strategy_implemented : {_strategy_implemented(definition)}")
    print(f"opened               : {gate.opened}")
    print(f"status               : {gate.reason}")
    if not gate.opened:
        raise SystemExit(3)


if __name__ == "__main__":
    asyncio.run(main())
