"""PostgreSQL 17 integration checks for migrations and RAW -> DDS ETL."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.integration

DATABASE_URL = os.getenv("TEST_DATABASE_URL")
PROJECT_ROOT = Path(__file__).parents[2]
MIGRATIONS = sorted((PROJECT_ROOT / "sql").glob("[0-9][0-9][0-9]_*.sql"))


def connect(conninfo=DATABASE_URL, *, autocommit=False):
    if not DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return psycopg.connect(conninfo, autocommit=autocommit)


def apply_all_migrations(connection) -> None:
    for migration in MIGRATIONS:
        with connection.cursor() as cursor:
            cursor.execute(migration.read_text(encoding="utf-8-sig"))
        connection.commit()


@pytest.fixture(scope="module", autouse=True)
def isolated_database():
    """Run destructive migration checks without modifying the shared test DB."""
    database_name = f"crypto_pipeline_{uuid.uuid4().hex}"
    database_url = make_conninfo(DATABASE_URL, dbname=database_name)

    with connect(autocommit=True) as admin_connection:
        with admin_connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(database_name)
                )
            )

        try:
            with connect(database_url) as connection:
                apply_all_migrations(connection)
                apply_all_migrations(connection)
                yield connection
        finally:
            # conninfo_to_dict validates that teardown targets only the database
            # generated above, never the shared TEST_DATABASE_URL database.
            assert conninfo_to_dict(database_url)["dbname"] == database_name
            with admin_connection.cursor() as cursor:
                cursor.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                        sql.Identifier(database_name)
                    )
                )


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


def test_replay_as_of_does_not_filter_raw_loaded_later(isolated_database) -> None:
    """Event-time replay must accept RAW ingested after the replay timestamp."""
    base = datetime(2026, 7, 2, tzinfo=UTC)
    replay_as_of = base + timedelta(hours=2)
    loaded_after_replay_cutoff = replay_as_of + timedelta(hours=1)

    insert_raw_candle(
        isolated_database,
        open_time=base,
        close_time=base + timedelta(hours=1),
        loaded_at=loaded_after_replay_cutoff,
    )

    result = run_etl(isolated_database, replay_as_of)
    assert result[4:] == (1, 1, 0, 0)

    with isolated_database.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM dds.candle c
            JOIN dds.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_name = 'bybit'
              AND i.symbol = 'BTCUSDT'
              AND c.interval_code = '1h'
              AND c.open_time = %s
            """,
            (base,),
        )
        assert cursor.fetchone()[0] == 1

        cursor.execute(
            """
            SELECT last_loaded_at, last_run_at
            FROM dds.etl_checkpoint
            WHERE exchange_name = 'bybit'
              AND symbol = 'BTCUSDT'
              AND interval_code = '1h'
            """
        )
        last_loaded_at, last_run_at = cursor.fetchone()
        assert last_loaded_at == loaded_after_replay_cutoff
        assert last_run_at == replay_as_of
