"""
Check Database Connection Script.

This script verifies PostgreSQL connection and checks for required schemas.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg

from app.config.settings import settings


def check_database():
    """Check PostgreSQL connection and schemas."""
    print("=" * 60)
    print("PostgreSQL Connection Test")
    print("=" * 60)
    print()

    conn = None
    try:
        # Connect to PostgreSQL
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )
        print("Connection: OK")
        print()

        # Execute SELECT 1
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
            print(f"SELECT 1: {result[0]}")
        print()

        # Check schemas
        with conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name IN ('raw_bybit', 'dds', 'mart')
                ORDER BY schema_name
            """)
            schemas = [row[0] for row in cur.fetchall()]

            print("Schemas:")
            for schema in ['raw_bybit', 'dds', 'mart']:
                status = "EXISTS" if schema in schemas else "MISSING"
                print(f"  {schema}: {status}")
        print()

        # Check raw_bybit.bars table
        with conn.cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'raw_bybit'
                    AND table_name = 'bars'
                )
            """)
            exists = cur.fetchone()[0]
            print(f"raw_bybit.bars table: {'EXISTS' if exists else 'MISSING'}")
        print()

        # Check row count
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM raw_bybit.bars")
            count = cur.fetchone()[0]
            print(f"Rows in raw_bybit.bars: {count}")
        print()

        print("Database check: PASSED")

    except psycopg.OperationalError as e:
        print("Connection: FAILED")
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1
    finally:
        if conn:
            conn.close()

    print()
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = check_database()
    sys.exit(exit_code)
