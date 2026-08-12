"""Incrementally maintain the sealed independent holdout dataset.

Pipeline:
    Bybit closed 1h candles -> RAW -> DDS -> versioned indicators/regime -> health gate

This script never imports or executes the holdout strategy and never computes
performance metrics. A non-zero exit code means the data-health gate is not clean.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.collectors.candle_collector import CandleCollector  # noqa: E402
from app.collectors.indicator_batch_collector import BatchIndicatorCollector  # noqa: E402
from app.database.connection import async_session_factory  # noqa: E402
from app.exchange.bybit_client import BybitClient  # noqa: E402
from app.exchange.intervals import interval_duration  # noqa: E402
from app.reporting.holdout_validation import (  # noqa: E402
    HoldoutDefinition,
    completed_interval_end,
    holdout_from_dict,
)

DEFAULT_DEFINITION = Path("config/validation/breakout_retest_v2_holdout.json")
HEALTH_SCRIPT = Path("scripts/holdout_validation.py")
# EMA-200 becomes available after 200 observations. The regime model uses a
# 10-value EMA-200 slope, so the first holdout candle needs 208 completed
# candles before it (indices 0..208 make both values available at index 208).
DERIVED_WARMUP_BARS = 208


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally update the sealed independent holdout dataset"
    )
    parser.add_argument("--definition", type=Path, default=DEFAULT_DEFINITION)
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="UTC/timezone-aware timestamp used for deterministic maintenance tests",
    )
    return parser.parse_args()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("update timestamp must be timezone-aware")
    return value.astimezone(timezone.utc)


def _load_definition(path: Path) -> HoldoutDefinition:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return holdout_from_dict(payload)


def next_collection_start(
    definition: HoldoutDefinition,
    checkpoint: datetime | None,
) -> datetime:
    """Return the first candle open_time not covered by a successful checkpoint."""
    duration = interval_duration(definition.interval)
    warmup_start = definition.period_start - duration * DERIVED_WARMUP_BARS
    if checkpoint is None:
        return warmup_start
    return max(warmup_start, _utc(checkpoint) + duration)


async def collect_closed_raw(
    definition: HoldoutDefinition,
    *,
    as_of: datetime,
) -> dict[str, int]:
    """Fetch only candles that are closed at ``as_of`` using collector checkpoints."""
    closed_end = completed_interval_end(definition, now=as_of)
    loaded: dict[str, int] = {}
    exchange = BybitClient()
    collector = CandleCollector(exchange)
    try:
        for symbol in definition.symbols:
            checkpoint = await collector.get_last_checkpoint(symbol, definition.interval)
            start = next_collection_start(definition, checkpoint)
            if start >= closed_end:
                loaded[symbol] = 0
                print(
                    f"RAW {symbol}: up-to-date start={start.isoformat()} "
                    f"closed_end={closed_end.isoformat()}"
                )
                continue

            count = await collector.load_historical_candles(
                symbol=symbol,
                interval=definition.interval,
                start_date=start,
                end_date=closed_end,
            )
            loaded[symbol] = count
            print(
                f"RAW {symbol}: loaded={count} range={start.isoformat()} -> "
                f"{closed_end.isoformat()}"
            )
    finally:
        await exchange.close()
    return loaded


async def load_raw_to_dds(
    definition: HoldoutDefinition,
    *,
    as_of: datetime,
) -> dict[str, int]:
    """Run the existing idempotent RAW -> DDS function per holdout symbol."""
    cutoff = _utc(as_of)
    inserted: dict[str, int] = {}
    for symbol in definition.symbols:
        async with async_session_factory() as session, session.begin():
            result = await session.execute(
                text(
                    """
                    SELECT * FROM dds.load_raw_candles(
                        :exchange, :symbol, :interval, :as_of
                    )
                    """
                ),
                {
                    "exchange": definition.exchange,
                    "symbol": symbol,
                    "interval": definition.interval,
                    "as_of": cutoff,
                },
            )
            rows = result.mappings().all()

        if not rows:
            inserted[symbol] = 0
            print(f"DDS {symbol}: no matching RAW stream")
            continue

        inserted_count = sum(int(row["inserted_count"]) for row in rows)
        rejected_count = sum(int(row["rejected_count"]) for row in rows)
        deferred_count = sum(int(row["deferred_count"]) for row in rows)
        if rejected_count or deferred_count:
            raise RuntimeError(
                f"DDS load not clean for {symbol}: rejected={rejected_count} "
                f"deferred={deferred_count}"
            )
        inserted[symbol] = inserted_count
        print(
            f"DDS {symbol}: inserted={inserted_count} rejected={rejected_count} "
            f"deferred={deferred_count}"
        )
    return inserted


async def calculate_missing_derived(
    definition: HoldoutDefinition,
    *,
    as_of: datetime,
) -> dict[str, int]:
    """Persist only incomplete current-version derived rows inside the holdout."""
    end = completed_interval_end(definition, now=as_of)
    collector = BatchIndicatorCollector(
        indicator_model_version=definition.indicator_model_version,
        regime_model_version=definition.regime_model_version,
    )
    processed: dict[str, int] = {}
    for symbol in definition.symbols:
        count = await collector.calculate_and_store_missing_indicators(
            symbol=symbol,
            interval=definition.interval,
            start_time=definition.period_start,
            end_time=end,
        )
        processed[symbol] = count
        print(f"DERIVED {symbol}: processed={count}")
    return processed


def run_health_gate(
    definition_path: Path,
    *,
    as_of: datetime,
) -> int:
    """Run the existing sealed data-health CLI using the same maintenance timestamp."""
    command = [
        sys.executable,
        str(HEALTH_SCRIPT),
        "--definition",
        str(definition_path),
        "health",
        "--as-of",
        _utc(as_of).isoformat(),
    ]
    completed = subprocess.run(command, check=False)
    return int(completed.returncode)


async def main() -> None:
    args = parse_args()
    definition = _load_definition(args.definition)
    as_of = (
        datetime.now(timezone.utc)
        if args.as_of is None
        else _utc(datetime.fromisoformat(args.as_of))
    )

    print("SEALED HOLDOUT INCREMENTAL UPDATE")
    print("=================================")
    print(f"validation_id       : {definition.validation_id}")
    print(f"as_of               : {as_of.isoformat()}")
    print(f"completed_through   : {completed_interval_end(definition, now=as_of).isoformat()}")
    print("performance_access  : SEALED")
    print("strategy_execution  : DISABLED")
    print()

    await collect_closed_raw(definition, as_of=as_of)
    await load_raw_to_dds(definition, as_of=as_of)
    await calculate_missing_derived(definition, as_of=as_of)

    print()
    health_code = run_health_gate(args.definition, as_of=as_of)
    if health_code != 0:
        print(f"update_status       : FAIL (health_exit_code={health_code})")
        raise SystemExit(health_code)

    print("update_status       : PASS")


if __name__ == "__main__":
    asyncio.run(main())
