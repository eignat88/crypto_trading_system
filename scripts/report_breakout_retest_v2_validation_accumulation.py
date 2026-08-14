from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.database.connection import async_session_factory
from app.reporting.breakout_retest_v2_validation_accumulation import (
    REQUIRED_SYMBOLS,
    VALIDATION_END,
    VALIDATION_START,
    StructuralCandleRecord,
    build_accumulation_status,
    effective_cutoff,
)


def _parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    result = datetime.fromisoformat(normalized)
    if result.tzinfo is None:
        raise ValueError("--as-of must be timezone-aware")
    return result.astimezone(UTC)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


async def _load_structural_records(
    *,
    symbol: str,
    cutoff: datetime,
) -> list[StructuralCandleRecord]:
    query = text(
        """
        SELECT
            c.candle_id,
            i.symbol,
            c.interval_code,
            c.open_time,
            (ema20.indicator_value IS NOT NULL) AS has_ema20,
            (ema50.indicator_value IS NOT NULL) AS has_ema50,
            (ema200.indicator_value IS NOT NULL) AS has_ema200,
            (mr.regime IS NOT NULL) AS has_regime
        FROM dds.candle c
        JOIN dds.instrument i
          ON i.instrument_id = c.instrument_id
        LEFT JOIN dds.indicator ema20
          ON ema20.candle_id = c.candle_id
         AND ema20.indicator_name = 'EMA'
         AND ema20.indicator_params = '{"period": 20}'::jsonb
        LEFT JOIN dds.indicator ema50
          ON ema50.candle_id = c.candle_id
         AND ema50.indicator_name = 'EMA'
         AND ema50.indicator_params = '{"period": 50}'::jsonb
        LEFT JOIN dds.indicator ema200
          ON ema200.candle_id = c.candle_id
         AND ema200.indicator_name = 'EMA'
         AND ema200.indicator_params = '{"period": 200}'::jsonb
        LEFT JOIN dds.market_regime mr
          ON mr.candle_id = c.candle_id
        WHERE i.exchange_name = 'bybit'
          AND i.symbol = :symbol
          AND c.interval_code = '1h'
          AND c.open_time >= :start
          AND c.open_time < :cutoff
          AND c.is_valid = true
        ORDER BY c.open_time ASC
        """
    )
    async with async_session_factory() as session:
        result = await session.execute(
            query,
            {
                "symbol": symbol,
                "start": VALIDATION_START,
                "cutoff": cutoff,
            },
        )
        rows = result.fetchall()

    return [
        StructuralCandleRecord(
            candle_id=int(row.candle_id),
            symbol=str(row.symbol),
            interval=str(row.interval_code),
            open_time=row.open_time,
            has_ema20=bool(row.has_ema20),
            has_ema50=bool(row.has_ema50),
            has_ema200=bool(row.has_ema200),
            has_regime=bool(row.has_regime),
        )
        for row in rows
    ]


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Safe Breakout Retest v2 future-holdout accumulation status. "
            "Does not load OHLC, run a strategy, or calculate performance."
        )
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Optional timezone-aware timestamp; defaults to current UTC time",
    )
    args = parser.parse_args()

    as_of = datetime.now(UTC) if args.as_of is None else _parse_datetime(args.as_of)
    cutoff = effective_cutoff(as_of)
    records_by_symbol = {
        symbol: await _load_structural_records(symbol=symbol, cutoff=cutoff)
        for symbol in REQUIRED_SYMBOLS
    }
    status = build_accumulation_status(records_by_symbol=records_by_symbol, as_of=as_of)

    print("BREAKOUT RETEST v2 — VALIDATION DATA ACCUMULATION STATUS")
    print("=========================================================")
    print(f"status                         : {status.status}")
    print(f"as_of                          : {status.as_of.isoformat()}")
    print(f"validation_start               : {VALIDATION_START.isoformat()}")
    print(f"validation_end                 : {VALIDATION_END.isoformat()}")
    print(f"elapsed_days                   : {status.elapsed_days}/{status.target_days}")
    print(f"remaining_days                 : {status.remaining_days}")
    print(
        "elapsed_expected_candles       : "
        f"{status.elapsed_expected_candles_per_symbol}/{status.target_candles_per_symbol} per symbol"
    )
    print(f"performance_opened             : {status.performance_opened}")
    print(f"strategy_executed              : {status.strategy_executed}")
    print(f"ohlc_loaded                    : {status.ohlc_loaded}")
    print(f"structure_fingerprint          : {status.structure_fingerprint}")

    for item in status.symbols:
        print()
        print(
            f"{item.symbol}: candles={item.actual_candles}/{item.target_candles} "
            f"elapsed_expected={item.elapsed_expected_candles} "
            f"completion={item.completion_pct}%"
        )
        print(f"  latest_open_time             : {item.latest_open_time}")
        print(f"  gaps                         : {item.gaps}")
        print(f"  duplicates                   : {item.duplicates}")
        print(f"  missing_ema20                : {item.missing_ema20}")
        print(f"  missing_ema50                : {item.missing_ema50}")
        print(f"  missing_ema200               : {item.missing_ema200}")
        print(f"  missing_regime               : {item.missing_regime}")
        print(f"  elapsed_coverage_complete    : {item.elapsed_coverage_complete}")
        print(f"  frozen_inputs_ready          : {item.frozen_inputs_ready}")
        print(f"  passed_so_far                : {item.passed_so_far}")

    if status.reasons:
        print()
        print("REASONS")
        print("-------")
        for reason in status.reasons:
            print(reason)

    output_dir = Path("artifacts/engineering")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"breakout_retest_v2_validation_accumulation_{stamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(UTC),
                    "purpose": "holdout data accumulation health only; no performance",
                    "strategy_executed": False,
                    "performance_calculated": False,
                    "performance_opened": False,
                    "ohlc_loaded": False,
                },
                "result": asdict(status),
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print()
    print(f"artifact                       : {artifact}")


if __name__ == "__main__":
    asyncio.run(main())
