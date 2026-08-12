from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

from app.database.connection import async_session_factory
from app.reporting.holdout_validation import (
    HoldoutSpec,
    SymbolHoldoutHealth,
    assess_holdout,
    completed_candle_cutoff,
    expected_closed_candles,
    load_holdout_spec,
)

DEFAULT_SPEC = Path("config/validation/breakout_retest_v2_holdout.json")


async def _load_symbol_health(
    spec: HoldoutSpec,
    symbol: str,
    *,
    now: datetime,
) -> SymbolHoldoutHealth:
    cutoff = completed_candle_cutoff(spec, now)
    expected_count = expected_closed_candles(spec, now)
    query = text(
        """
        SELECT
            c.open_time,
            EXISTS (
                SELECT 1
                FROM dds.market_regime mr
                WHERE mr.candle_id = c.candle_id
                  AND mr.indicator_model_version = :indicator_model_version
                  AND mr.regime_model_version = :regime_model_version
            ) AS has_regime
        FROM dds.candle c
        JOIN dds.instrument i ON i.instrument_id = c.instrument_id
        WHERE i.exchange_name = :exchange
          AND i.symbol = :symbol
          AND c.interval_code = :interval
          AND c.open_time >= :period_start
          AND c.open_time < :cutoff
          AND c.is_valid = true
        ORDER BY c.open_time
        """
    )
    async with async_session_factory() as session:
        result = await session.execute(
            query,
            {
                "exchange": spec.exchange,
                "symbol": symbol,
                "interval": spec.interval,
                "period_start": spec.period_start,
                "cutoff": cutoff,
                "indicator_model_version": spec.indicator_model_version,
                "regime_model_version": spec.regime_model_version,
            },
        )
        rows = [dict(row._mapping) for row in result.fetchall()]

    observed_times = [row["open_time"].astimezone(timezone.utc) for row in rows]
    unique_times = set(observed_times)
    duplicate_count = len(observed_times) - len(unique_times)
    expected_times = {
        spec.period_start + timedelta(hours=offset)
        for offset in range(expected_count)
    }
    missing_count = len(expected_times - unique_times)
    derived_count = sum(bool(row["has_regime"]) for row in rows)

    return SymbolHoldoutHealth(
        symbol=symbol,
        expected_closed_candles=expected_count,
        observed_candles=len(observed_times),
        derived_regimes=derived_count,
        duplicate_candles=duplicate_count,
        missing_candles=missing_count,
        first_open_time=min(observed_times) if observed_times else None,
        last_open_time=max(observed_times) if observed_times else None,
    )


async def _status(spec_path: Path, *, assert_openable: bool) -> None:
    spec = load_holdout_spec(spec_path)
    now = datetime.now(timezone.utc)
    health = tuple(
        [
            await _load_symbol_health(spec, symbol, now=now)
            for symbol in spec.symbols
        ]
    )
    status = assess_holdout(spec, now=now, symbol_health=health)

    print("INDEPENDENT HOLDOUT STATUS")
    print("==========================")
    print(f"name                   : {spec.name}")
    print(f"strategy_spec          : {spec.strategy_spec_version}")
    print(f"implementation_status  : {spec.implementation_status}")
    print(f"period                 : {spec.period_start.isoformat()} -> {spec.period_end.isoformat()}")
    print(f"cutoff                 : {status.cutoff.isoformat()}")
    print(f"indicator_model        : {spec.indicator_model_version}")
    print(f"regime_model           : {spec.regime_model_version}")
    print(f"execution_model        : {spec.execution_model_version}")
    print(f"state                  : {status.state}")
    print(f"performance_access     : {'OPEN' if status.performance_access_allowed else 'SEALED'}")

    for item in status.symbols:
        print()
        print(item.symbol)
        print(f"  expected_closed      : {item.expected_closed_candles}")
        print(f"  observed             : {item.observed_candles}")
        print(f"  derived_regimes      : {item.derived_regimes}")
        print(f"  missing              : {item.missing_candles}")
        print(f"  duplicates           : {item.duplicate_candles}")
        print(f"  data_health          : {'PASS' if item.healthy else 'FAIL'}")

    if status.reasons:
        print()
        print("reasons:")
        for reason in status.reasons:
            print(f"  - {reason}")

    if assert_openable and not status.performance_access_allowed:
        raise RuntimeError(
            "HOLDOUT_SEALED: strategy performance access is not allowed"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect independent holdout data health without exposing strategy performance"
    )
    parser.add_argument("command", choices=("status", "assert-openable"))
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    await _status(args.spec, assert_openable=args.command == "assert-openable")


if __name__ == "__main__":
    asyncio.run(main())
