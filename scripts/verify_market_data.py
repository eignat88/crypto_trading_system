"""Read-only verification of one historical candle range in RAW and DDS."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config.settings import settings
from app.exchange.intervals import interval_duration


def utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a half-open candle range [start, end)")
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--symbol", required=True, choices=("BTCUSDT", "ETHUSDT"))
    parser.add_argument("--interval", required=True, choices=("5m", "15m", "1h", "4h", "1d"))
    parser.add_argument("--start", required=True, type=utc_datetime)
    parser.add_argument("--end", required=True, type=utc_datetime)
    parser.add_argument("--layer", choices=("raw", "dds", "all"), default="all")
    parser.add_argument(
        "--database-url",
        help="SQLAlchemy sync URL; defaults to DATABASE_URL_SYNC from the environment",
    )
    return parser.parse_args()


def _scalar(connection: Any, statement: str, params: dict[str, Any]) -> int:
    return int(connection.execute(text(statement), params).scalar_one())


def verify(args: argparse.Namespace) -> tuple[dict[str, Any], list[str]]:
    duration = interval_duration(args.interval)
    if args.end <= args.start:
        raise ValueError("--end must be later than --start")
    seconds = (args.end - args.start).total_seconds()
    if seconds % duration.total_seconds() != 0:
        raise ValueError("The requested range must contain whole candle intervals")

    expected_count = int(seconds // duration.total_seconds())
    params = {
        "exchange": args.exchange,
        "symbol": args.symbol,
        "interval": args.interval,
        "start": args.start,
        "end": args.end,
        "step_seconds": int(duration.total_seconds()),
    }
    report: dict[str, Any] = {
        "stream": f"{args.exchange}:{args.symbol}:{args.interval}",
        "range": {"start": args.start.isoformat(), "end": args.end.isoformat()},
        "expected_count": expected_count,
    }
    failures: list[str] = []
    engine = create_engine(args.database_url or settings.database_url_sync, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            raw_count = _scalar(
                connection,
                """
                SELECT count(*) FROM raw_market.candles
                WHERE exchange_name=:exchange AND symbol=:symbol
                  AND interval_code=:interval AND open_time >= :start AND open_time < :end
                """,
                params,
            )
            raw_gaps = _scalar(
                connection,
                """
                WITH ordered AS (
                    SELECT open_time, lag(open_time) OVER (ORDER BY open_time) AS previous_time
                    FROM raw_market.candles
                    WHERE exchange_name=:exchange AND symbol=:symbol
                      AND interval_code=:interval AND open_time >= :start AND open_time < :end
                )
                SELECT count(*) FROM ordered
                WHERE previous_time IS NOT NULL
                  AND extract(epoch FROM open_time - previous_time) <> :step_seconds
                """,
                params,
            )
            raw_invalid = _scalar(
                connection,
                """
                SELECT count(*) FROM raw_market.candles
                WHERE exchange_name=:exchange AND symbol=:symbol AND interval_code=:interval
                  AND open_time >= :start AND open_time < :end
                  AND (close_time IS NULL OR close_time <= open_time
                       OR open_price <= 0 OR high_price <= 0 OR low_price <= 0
                       OR close_price <= 0 OR high_price < greatest(open_price, close_price)
                       OR low_price > least(open_price, close_price) OR high_price < low_price
                       OR coalesce(volume, 0) < 0 OR quote_volume < 0 OR trade_count < 0)
                """,
                params,
            )
            report["raw"] = {
                "count": raw_count,
                "gaps": raw_gaps,
                "invalid": raw_invalid,
            }
            if raw_count != expected_count:
                failures.append(f"RAW count {raw_count} != expected {expected_count}")
            if raw_gaps:
                failures.append(f"RAW contains {raw_gaps} time-series gaps")
            if raw_invalid:
                failures.append(f"RAW contains {raw_invalid} invalid candles")

            if args.layer in {"dds", "all"}:
                dds_count = _scalar(
                    connection,
                    """
                    SELECT count(*) FROM dds.candle c
                    JOIN dds.instrument i ON i.instrument_id = c.instrument_id
                    WHERE i.exchange_name=:exchange AND i.symbol=:symbol
                      AND c.interval_code=:interval
                      AND c.open_time >= :start AND c.open_time < :end
                    """,
                    params,
                )
                dds_gaps = _scalar(
                    connection,
                    """
                    WITH ordered AS (
                        SELECT c.open_time,
                               lag(c.open_time) OVER (ORDER BY c.open_time) AS previous_time
                        FROM dds.candle c
                        JOIN dds.instrument i ON i.instrument_id = c.instrument_id
                        WHERE i.exchange_name=:exchange AND i.symbol=:symbol
                          AND c.interval_code=:interval
                          AND c.open_time >= :start AND c.open_time < :end
                    )
                    SELECT count(*) FROM ordered
                    WHERE previous_time IS NOT NULL
                      AND extract(epoch FROM open_time - previous_time) <> :step_seconds
                    """,
                    params,
                )
                quality_events = _scalar(
                    connection,
                    """
                    SELECT count(*) FROM dds.data_quality_event
                    WHERE exchange_name=:exchange AND symbol=:symbol
                      AND interval_code=:interval AND open_time >= :start AND open_time < :end
                    """,
                    params,
                )
                latest_run = connection.execute(
                    text(
                        """
                        SELECT status, source_count, inserted_count, rejected_count, deferred_count
                        FROM dds.etl_run
                        WHERE exchange_name=:exchange AND symbol=:symbol AND interval_code=:interval
                        ORDER BY run_id DESC LIMIT 1
                        """
                    ),
                    params,
                ).mappings().one_or_none()
                checkpoint = connection.execute(
                    text(
                        """
                        SELECT last_loaded_at, last_run_at
                        FROM dds.etl_checkpoint
                        WHERE exchange_name=:exchange AND symbol=:symbol AND interval_code=:interval
                        """
                    ),
                    params,
                ).mappings().one_or_none()
                report["dds"] = {
                    "count": dds_count,
                    "gaps": dds_gaps,
                    "quality_events": quality_events,
                    "latest_run": dict(latest_run) if latest_run else None,
                    "checkpoint": {
                        key: value.isoformat() for key, value in checkpoint.items()
                    } if checkpoint else None,
                }
                if dds_count != expected_count:
                    failures.append(f"DDS count {dds_count} != expected {expected_count}")
                if dds_gaps:
                    failures.append(f"DDS contains {dds_gaps} time-series gaps")
                if quality_events:
                    failures.append(f"DDS contains {quality_events} quality events")
                if latest_run is None or latest_run["status"] != "success":
                    failures.append("No successful DDS ETL run found")
    finally:
        engine.dispose()
    return report, failures


def main() -> None:
    args = parse_args()
    report, failures = verify(args)
    report["status"] = "failed" if failures else "success"
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
