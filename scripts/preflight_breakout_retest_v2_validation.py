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
from app.reporting.breakout_retest_v2_validation_preflight import (
    REQUIRED_INTERVAL,
    REQUIRED_SYMBOLS,
    STATUS_READY,
    StructuralCandleRecord,
    dataset_structure_fingerprint,
    run_preflight,
)


def parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    result = datetime.fromisoformat(normalized)
    if result.tzinfo is None:
        raise ValueError("validation timestamps must include timezone")
    return result.astimezone(UTC)


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


async def load_structural_records(
    *,
    exchange: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[StructuralCandleRecord]:
    """Load only structure/readiness metadata. OHLC values are intentionally absent."""
    query = text(
        """
        SELECT
            c.candle_id,
            i.symbol,
            c.interval_code,
            c.open_time,
            EXISTS (
                SELECT 1 FROM dds.indicator x
                WHERE x.candle_id = c.candle_id
                  AND x.indicator_name = 'EMA'
                  AND x.indicator_params = '{"period": 20}'::jsonb
            ) AS has_ema20,
            EXISTS (
                SELECT 1 FROM dds.indicator x
                WHERE x.candle_id = c.candle_id
                  AND x.indicator_name = 'EMA'
                  AND x.indicator_params = '{"period": 50}'::jsonb
            ) AS has_ema50,
            EXISTS (
                SELECT 1 FROM dds.indicator x
                WHERE x.candle_id = c.candle_id
                  AND x.indicator_name = 'EMA'
                  AND x.indicator_params = '{"period": 200}'::jsonb
            ) AS has_ema200,
            EXISTS (
                SELECT 1 FROM dds.market_regime mr
                WHERE mr.candle_id = c.candle_id
            ) AS has_regime
        FROM dds.candle c
        JOIN dds.instrument i
          ON i.instrument_id = c.instrument_id
        WHERE i.exchange_name = :exchange
          AND i.symbol = :symbol
          AND c.interval_code = :interval
          AND c.open_time >= :start
          AND c.open_time < :end
          AND c.is_valid = true
        ORDER BY c.open_time ASC
        """
    )
    async with async_session_factory() as session:
        result = await session.execute(
            query,
            {
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
                "start": start,
                "end": end,
            },
        )
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
            for row in result.fetchall()
        ]


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Breakout Retest v2 independent-validation preflight. "
            "Does not load OHLC, execute strategies, or calculate performance."
        )
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--provenance-id", required=True)
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--interval", default=REQUIRED_INTERVAL)
    args = parser.parse_args()

    if args.interval != REQUIRED_INTERVAL:
        raise ValueError(f"validation interval is frozen at {REQUIRED_INTERVAL}")

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    records_by_symbol = {
        symbol: await load_structural_records(
            exchange=args.exchange,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
        )
        for symbol in REQUIRED_SYMBOLS
    }

    result = run_preflight(
        records_by_symbol=records_by_symbol,
        start=start,
        end=end,
        provenance_id=args.provenance_id,
        repo_root=Path(__file__).resolve().parents[1],
    )
    structure_fingerprint = dataset_structure_fingerprint(records_by_symbol)

    print("BREAKOUT RETEST v2 — INDEPENDENT VALIDATION PREFLIGHT")
    print("======================================================")
    print(f"status                 : {result.status}")
    print(f"provenance_id          : {result.provenance_id}")
    print(f"period                 : {result.start.isoformat()} .. {result.end.isoformat()}")
    print(f"duration_days          : {result.duration_days}")
    print(f"temporal_segments_60d  : {result.temporal_segments}")
    print(f"strategy_executed      : {result.strategy_executed}")
    print(f"performance_calculated : {result.performance_calculated}")
    print(f"trade_count_gate       : {result.trade_count_gate}")
    print(f"structure_fingerprint  : {structure_fingerprint}")
    print()

    for item in result.symbols:
        print(
            f"{item.symbol}: candles={item.candle_count}/{item.expected_candle_count} "
            f"gaps={item.gaps} duplicates={item.duplicates} "
            f"missing_ema20={item.missing_ema20} missing_ema50={item.missing_ema50} "
            f"missing_ema200={item.missing_ema200} missing_regime={item.missing_regime} "
            f"passed={item.passed}"
        )

    print()
    print("FROZEN FILE INTEGRITY")
    print("---------------------")
    for item in result.integrity:
        print(f"{item.path}: matched={item.matched} sha256={item.sha256}")

    if result.reasons:
        print()
        print("REASONS")
        print("-------")
        for reason in result.reasons:
            print(reason)

    output_dir = Path("artifacts/engineering")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"breakout_retest_v2_validation_preflight_{timestamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(UTC),
                    "purpose": "independent validation preflight only",
                    "strategy_executed": False,
                    "performance_calculated": False,
                    "ohlc_loaded": False,
                    "trade_count_gate": result.trade_count_gate,
                    "dataset_structure_fingerprint": structure_fingerprint,
                },
                "result": asdict(result),
            },
            indent=2,
            ensure_ascii=False,
            default=json_default,
        ),
        encoding="utf-8",
    )
    print()
    print(f"artifact               : {artifact}")

    if result.status != STATUS_READY:
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
