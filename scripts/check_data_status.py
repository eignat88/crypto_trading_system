"""
Check Data Status Script.

This script shows the status of data in raw_bybit.bars and dds.candle.

Usage:
    python scripts/check_data_status.py
"""

import sys
from pathlib import Path

import psycopg

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import settings


def check_data_status():
    """Check and display data status."""
    conn = psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
    )

    try:
        with conn.cursor() as cur:
            print("=" * 60)
            print("Data Status Report")
            print("=" * 60)
            print()

            # Check raw_bybit.bars
            print("RAW (raw_bybit.bars):")
            print("-" * 40)

            cur.execute("""
                SELECT
                    instrument_id,
                    COUNT(*) as row_count,
                    MIN(ts_event) as earliest,
                    MAX(ts_event) as latest
                FROM raw_bybit.bars
                GROUP BY instrument_id
                ORDER BY instrument_id
            """)
            raw_rows = cur.fetchall()

            if raw_rows:
                for row in raw_rows:
                    print(f"  {row[0]}:")
                    print(f"    Rows: {row[1]}")
                    print(f"    Earliest: {row[2]}")
                    print(f"    Latest: {row[3]}")
            else:
                print("  No data")
            print()

            # Check dds.candle
            print("DDS (dds.candle):")
            print("-" * 40)

            cur.execute("""
                SELECT
                    i.symbol,
                    c.interval_code,
                    COUNT(*) as row_count,
                    MIN(c.open_time) as earliest,
                    MAX(c.open_time) as latest
                FROM dds.candle c
                JOIN dds.instrument i ON c.instrument_id = i.instrument_id
                GROUP BY i.symbol, c.interval_code
                ORDER BY i.symbol, c.interval_code
            """)
            dds_rows = cur.fetchall()

            if dds_rows:
                for row in dds_rows:
                    print(f"  {row[0]} ({row[1]}):")
                    print(f"    Rows: {row[2]}")
                    print(f"    Earliest: {row[3]}")
                    print(f"    Latest: {row[4]}")
            else:
                print("  No data")
            print()

            # Check data quality events
            print("Data Quality Events:")
            print("-" * 40)

            cur.execute("""
                SELECT
                    symbol,
                    check_name,
                    COUNT(*) as event_count
                FROM dds.data_quality_event
                GROUP BY symbol, check_name
                ORDER BY symbol, check_name
            """)
            quality_rows = cur.fetchall()

            if quality_rows:
                for row in quality_rows:
                    print(f"  {row[0]} - {row[1]}: {row[2]} events")
            else:
                print("  No quality events")
            print()

            # ETL status
            print("ETL Checkpoints:")
            print("-" * 40)

            cur.execute("""
                SELECT
                    symbol,
                    interval_code,
                    last_loaded_at,
                    last_run_at
                FROM dds.etl_checkpoint
                ORDER BY symbol, interval_code
            """)
            etl_rows = cur.fetchall()

            if etl_rows:
                for row in etl_rows:
                    print(f"  {row[0]} ({row[1]}):")
                    print(f"    Last loaded: {row[2]}")
                    print(f"    Last run: {row[3]}")
            else:
                print("  No ETL checkpoints")
            print()

            print("=" * 60)

    finally:
        conn.close()


if __name__ == "__main__":
    check_data_status()
