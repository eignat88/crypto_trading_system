"""
ETL Script: raw_bybit.bars → dds.candle

This script transfers candle data from raw_bybit.bars to dds.candle
with quality checks and idempotent loading.

Usage:
    python scripts/etl_raw_to_dds.py
    python scripts/etl_raw_to_dds.py --symbol BTCUSDT
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import settings


def parse_args():
    parser = argparse.ArgumentParser(description="ETL raw_bybit.bars to dds.candle")
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Process only this symbol (default: all)",
    )
    parser.add_argument(
        "--interval",
        type=str,
        default=None,
        help="Process only this interval (default: all)",
    )
    return parser.parse_args()


def validate_candle(row: dict) -> list[str]:
    """Validate a candle row and return list of errors."""
    errors = []

    # Check OHLC consistency
    if row["high_price"] < row["open_price"]:
        errors.append("high < open")
    if row["high_price"] < row["close_price"]:
        errors.append("high < close")
    if row["low_price"] > row["open_price"]:
        errors.append("low > open")
    if row["low_price"] > row["close_price"]:
        errors.append("low > close")
    if row["high_price"] < row["low_price"]:
        errors.append("high < low")

    # Check prices are positive
    if row["open_price"] <= 0:
        errors.append("open <= 0")
    if row["high_price"] <= 0:
        errors.append("high <= 0")
    if row["low_price"] <= 0:
        errors.append("low <= 0")
    if row["close_price"] <= 0:
        errors.append("close <= 0")

    # Check volume
    if row["volume"] < 0:
        errors.append("volume < 0")

    return errors


def run_etl(symbol: str = None, interval: str = None) -> dict:
    """Run ETL from raw_bybit.bars to dds.candle."""
    conn = psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )

    stats = {
        "source_count": 0,
        "inserted_count": 0,
        "rejected_count": 0,
        "errors": [],
    }

    try:
        with conn.cursor() as cur:
            # Get instruments
            cur.execute("""
                SELECT instrument_id, symbol
                FROM dds.instrument
                WHERE exchange_name = 'bybit'
            """)
            instruments = {row[0]: row[1] for row in cur.fetchall()}

            # Get raw bars
            query = """
                SELECT id, instrument_id, bar_type, ts_event, ts_init,
                       open_price, high_price, low_price, close_price, volume
                FROM raw_bybit.bars
                WHERE 1=1
            """
            params = []

            if symbol:
                query += " AND instrument_id = %s"
                params.append(f"{symbol}-SPOT.BYBIT")

            if interval:
                query += " AND bar_type LIKE %s"
                params.append(f"%{interval}%")

            query += " ORDER BY ts_event"

            cur.execute(query, params)
            raw_bars = cur.fetchall()

            stats["source_count"] = len(raw_bars)

            for bar in raw_bars:
                bar_id = bar[0]
                instrument_id = bar[1]
                bar_type = bar[2]
                ts_event = bar[3]
                ts_init = bar[4]
                open_price = bar[5]
                high_price = bar[6]
                low_price = bar[7]
                close_price = bar[8]
                volume = bar[9]

                # Validate
                errors = validate_candle({
                    "open_price": open_price,
                    "high_price": high_price,
                    "low_price": low_price,
                    "close_price": close_price,
                    "volume": volume,
                })

                if errors:
                    # Store quality event
                    cur.execute("""
                        INSERT INTO dds.data_quality_event (
                            exchange_name, symbol, interval_code, open_time,
                            check_name, error_details
                        ) VALUES (
                            'bybit', %s, %s, %s,
                            'ohlc_validation', %s
                        )
                        ON CONFLICT (exchange_name, symbol, interval_code, open_time, check_name)
                        DO UPDATE SET
                            last_seen_at = now(),
                            occurrence_count = dds.data_quality_event.occurrence_count + 1,
                            error_details = EXCLUDED.error_details
                    """, (
                        instruments.get(instrument_id, "UNKNOWN"),
                        bar_type.split("-")[0] if "-" in bar_type else "1h",
                        ts_event,
                        {"errors": errors},
                    ))
                    stats["rejected_count"] += 1
                    continue

                # Get interval_code from bar_type
                interval_code = bar_type.split("-")[1] if "-" in bar_type else "1h"

                # Insert into dds.candle
                cur.execute("""
                    INSERT INTO dds.candle (
                        instrument_id, interval_code, open_time, close_time,
                        open_price, high_price, low_price, close_price, volume,
                        is_valid, validation_errors
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        true, NULL
                    )
                    ON CONFLICT (instrument_id, interval_code, open_time) DO NOTHING
                """, (
                    instrument_id,
                    interval_code,
                    ts_event,
                    ts_init,
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                ))

                if cur.rowcount > 0:
                    stats["inserted_count"] += 1

            conn.commit()

    except Exception as e:
        stats["errors"].append(str(e))
        conn.rollback()
        raise

    finally:
        conn.close()

    return stats


def main():
    args = parse_args()

    print("=" * 60)
    print("ETL: raw_bybit.bars → dds.candle")
    print("=" * 60)
    print()

    try:
        stats = run_etl(symbol=args.symbol, interval=args.interval)

        print(f"Source count: {stats['source_count']}")
        print(f"Inserted: {stats['inserted_count']}")
        print(f"Rejected: {stats['rejected_count']}")

        if stats["errors"]:
            print()
            print("Errors:")
            for error in stats["errors"]:
                print(f"  - {error}")

        print()
        print("=" * 60)

        if stats["rejected_count"] > 0:
            print("WARNING: Some candles were rejected due to quality issues.")
            print("Check dds.data_quality_event for details.")
            return 1

        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
