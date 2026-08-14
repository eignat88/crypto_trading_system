"""
Script to run DDS to MART ETL.

Usage:
    python scripts/load_mart.py                    # Full recalculation (yesterday)
    python scripts/load_mart.py --date 2026-08-14  # Recalculate specific date
"""

import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import structlog

# Add project root to path
sys_path = Path(__file__).parent.parent
import sys  # noqa: E402

sys.path.insert(0, str(sys_path))

from sqlalchemy import text  # noqa: E402

from app.database.connection import async_session_factory  # noqa: E402

# Configure logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger("info"),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def parse_args():
    parser = argparse.ArgumentParser(description="Run DDS to MART ETL")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date for ETL (YYYY-MM-DD). Default: yesterday",
    )
    parser.add_argument(
        "--exchange",
        type=str,
        default="bybit",
        help="Exchange name (default: bybit)",
    )
    parser.add_argument(
        "--no-log-run",
        action="store_true",
        help="Do not log this run in mart.etl_run table",
    )
    return parser.parse_args()


async def run_etl(target_date: str | None, exchange_name: str, log_run: bool):
    """Execute the MART ETL pipeline."""
    async with async_session_factory() as session:
        async with session.begin():
            # Build SQL call
            if target_date:
                sql = text(
                    """
                    SELECT daily_ohlcv_rows, strategy_perf_rows
                    FROM mart.run_etl(
                        p_exchange_name := :exchange_name,
                        p_target_date := :target_date::date,
                        p_log_run := :log_run
                    )
                    """
                )
                params = {
                    "exchange_name": exchange_name,
                    "target_date": target_date,
                    "log_run": log_run,
                }
            else:
                sql = text(
                    """
                    SELECT daily_ohlcv_rows, strategy_perf_rows
                    FROM mart.run_etl(
                        p_exchange_name := :exchange_name,
                        p_target_date := NULL,
                        p_log_run := :log_run
                    )
                    """
                )
                params = {
                    "exchange_name": exchange_name,
                    "log_run": log_run,
                }

            result = await session.execute(sql, params)
            rows = result.fetchall()

            if rows:
                daily_rows = sum(row[0] for row in rows)
                strategy_rows = sum(row[1] for row in rows)
                logger.info(
                    "etl_completed",
                    daily_ohlcv_rows=daily_rows,
                    strategy_performance_rows=strategy_rows,
                    total_rows=daily_rows + strategy_rows,
                )
                return daily_rows + strategy_rows
            else:
                logger.info("etl_completed_no_data")
                return 0


async def main():
    args = parse_args()

    # Parse date if provided
    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            logger.error("invalid_date_format", date=args.date)
            sys.exit(1)

    logger.info(
        "etl_started",
        target_date=target_date or "yesterday",
        exchange=args.exchange,
        log_run=not args.no_log_run,
    )

    try:
        rows_processed = await run_etl(
            target_date=target_date,
            exchange_name=args.exchange,
            log_run=not args.no_log_run,
        )
        logger.info("etl_finished", rows_processed=rows_processed)
    except Exception:
        logger.exception("etl_failed")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
