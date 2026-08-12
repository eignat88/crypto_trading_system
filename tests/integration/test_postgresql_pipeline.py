"""PostgreSQL 17 integration checks for migrations and RAW -> DDS ETL."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).parents[2]
MIGRATIONS = sorted((PROJECT_ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql"))


def connect():
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return psycopg.connect(DATABASE_URL)


def apply_all_migrations(connection) -> None:
    for migration in MIGRATIONS:
        with connection.cursor() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8-sig"))
        connection.commit()


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    connection = connect()
    with connection.cursor() as cursor:
        cursor.execute("DROP SCHEMA IF EXISTS mart CASCADE")
        cursor.execute("DROP SCHEMA IF EXISTS dds CASCADE")
        cursor.execute("DROP SCHEMA IF EXISTS raw_market CASCADE")
        cursor.execute("DROP SCHEMA IF EXISTS raw_account CASCADE")
        cursor.execute("DROP SCHEMA IF EXISTS raw_system CASCADE")
        cursor.execute("DROP TABLE IF EXISTS risk_events CASCADE")
        cursor.execute("DROP TABLE IF EXISTS risk_engine_state CASCADE")
    connection.commit()
    apply_all_migrations(connection)
    apply_all_migrations(connection)
    yield connection
    connection.close()


def insert_raw_candle(
    connection,
    *,
    open_time: datetime,
    close_time: datetime,
    loaded_at: datetime,
    high_price: Decimal = Decimal("101"),
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO raw_market.candles (
                exchange_name, symbol, interval_code, open_time, close_time,
                open_price, high_price, low_price, close_price, volume, loaded_at
            ) VALUES ('bybit', 'BTCUSDT', '1h', %s, %s, 100, %s, 99, 100.5, 10, %s)
            """,
            (open_time, close_time, high_price, loaded_at),
        )
    connection.commit()


def run_etl(connection, as_of: datetime):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT * FROM dds.load_raw_candles('bybit', 'BTCUSDT', '1h', %s)",
            (as_of,),
        )
        row = cursor.fetchone()
    connection.commit()
    return row


def test_migrations_create_required_database_contract(isolated_database) -> None:
    with isolated_database.cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass('raw_market.candles'),
                   to_regclass('dds.candle'),
                   to_regclass('dds.data_quality_event'),
                   to_regprocedure('dds.load_raw_candles(text,text,text,timestamptz)')
            """
        )
        assert all(cursor.fetchone())


def test_raw_to_dds_valid_rejected_deferred_and_retry(isolated_database) -> None:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    insert_raw_candle(
        isolated_database,
        open_time=base,
        close_time=base + timedelta(hours=1),
        loaded_at=base + timedelta(minutes=1),
    )
    insert_raw_candle(
        isolated_database,
        open_time=base + timedelta(hours=1),
        close_time=base + timedelta(hours=2),
        loaded_at=base + timedelta(minutes=2),
        high_price=Decimal("98"),
    )
    insert_raw_candle(
        isolated_database,
        open_time=base + timedelta(hours=2),
        close_time=base + timedelta(hours=3),
        loaded_at=base + timedelta(minutes=3),
    )

    first = run_etl(isolated_database, base + timedelta(hours=2, minutes=30))
    assert first[4:] == (2, 1, 1, 1)

    with isolated_database.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM dds.candle")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT check_name FROM dds.data_quality_event")
        assert cursor.fetchone()[0] == "invalid_ohlc"

    second = run_etl(isolated_database, base + timedelta(hours=2, minutes=30))
    assert second[4:] == (0, 0, 0, 0)

    after_close = run_etl(isolated_database, base + timedelta(hours=3))
    assert after_close[4:] == (1, 1, 0, 0)
    with isolated_database.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM dds.candle")
        assert cursor.fetchone()[0] == 2
        cursor.execute(
            """
            SELECT last_loaded_at, last_run_at FROM dds.etl_checkpoint
            WHERE exchange_name='bybit' AND symbol='BTCUSDT' AND interval_code='1h'
            """
        )
        last_loaded_at, last_run_at = cursor.fetchone()
        assert last_loaded_at == base + timedelta(minutes=3)
        assert last_run_at == base + timedelta(hours=3)
