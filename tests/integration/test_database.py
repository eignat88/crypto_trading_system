"""Integration test for PostgreSQL database."""

import pytest
import psycopg

from app.config.settings import settings


@pytest.mark.integration
class TestDatabase:
    """Integration tests for PostgreSQL database.

    These tests require a running PostgreSQL instance.
    """

    def test_connection(self):
        """Test PostgreSQL connection."""
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )

        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            result = cur.fetchone()
            assert result[0] == 1

        conn.close()

    def test_schemas_exist(self):
        """Test that required schemas exist."""
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )

        with conn.cursor() as cur:
            cur.execute("""
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name IN ('raw_bybit', 'dds', 'mart')
            """)
            schemas = {row[0] for row in cur.fetchall()}

            assert 'raw_bybit' in schemas, "raw_bybit schema missing"
            assert 'dds' in schemas, "dds schema missing"
            assert 'mart' in schemas, "mart schema missing"

        conn.close()

    def test_raw_bybit_bars_table(self):
        """Test that raw_bybit.bars table exists."""
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )

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
            assert exists, "raw_bybit.bars table missing"

        conn.close()

    def test_insert_and_duplicate_protection(self):
        """Test that duplicate insertion is prevented."""
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )

        try:
            with conn.cursor() as cur:
                # Insert a test bar
                cur.execute("""
                    INSERT INTO raw_bybit.bars (
                        instrument_id, bar_type, ts_event, ts_init,
                        open_price, high_price, low_price, close_price, volume
                    ) VALUES (
                        'BTCUSDT-SPOT.BYBIT', 'BTCUSDT-SPOT.BYBIT-1-MINUTE-LAST-EXTERNAL',
                        '2024-01-01 00:00:00+00', '2024-01-01 00:00:01+00',
                        42000, 42100, 41900, 42050, 100
                    )
                    ON CONFLICT DO NOTHING
                """)
                conn.commit()

                # Try to insert duplicate
                cur.execute("""
                    INSERT INTO raw_bybit.bars (
                        instrument_id, bar_type, ts_event, ts_init,
                        open_price, high_price, low_price, close_price, volume
                    ) VALUES (
                        'BTCUSDT-SPOT.BYBIT', 'BTCUSDT-SPOT.BYBIT-1-MINUTE-LAST-EXTERNAL',
                        '2024-01-01 00:00:00+00', '2024-01-01 00:00:01+00',
                        42000, 42100, 41900, 42050, 100
                    )
                    ON CONFLICT DO NOTHING
                """)
                conn.commit()

                # Check count
                cur.execute("""
                    SELECT COUNT(*)
                    FROM raw_bybit.bars
                    WHERE instrument_id = 'BTCUSDT-SPOT.BYBIT'
                    AND ts_event = '2024-01-01 00:00:00+00'
                """)
                count = cur.fetchone()[0]
                assert count == 1, f"Expected 1 row, got {count}"

                # Clean up
                cur.execute("""
                    DELETE FROM raw_bybit.bars
                    WHERE instrument_id = 'BTCUSDT-SPOT.BYBIT'
                    AND ts_event = '2024-01-01 00:00:00+00'
                """)
                conn.commit()

        finally:
            conn.close()

    def test_utc_timestamps(self):
        """Test that timestamps are stored in UTC."""
        conn = psycopg.connect(
            host=settings.postgres_host,
            port=settings.postgres_port,
            dbname=settings.postgres_db,
            user=settings.postgres_user,
            password=settings.postgres_password,
        )

        try:
            with conn.cursor() as cur:
                # Insert a test bar with UTC timestamp
                cur.execute("""
                    INSERT INTO raw_bybit.bars (
                        instrument_id, bar_type, ts_event, ts_init,
                        open_price, high_price, low_price, close_price, volume
                    ) VALUES (
                        'ETHUSDT-SPOT.BYBIT', 'ETHUSDT-SPOT.BYBIT-1-MINUTE-LAST-EXTERNAL',
                        '2024-06-15 12:00:00+00', '2024-06-15 12:00:01+00',
                        3500, 3510, 3490, 3505, 50
                    )
                    ON CONFLICT DO NOTHING
                """)
                conn.commit()

                # Check timestamp is in UTC
                cur.execute("""
                    SELECT ts_event
                    FROM raw_bybit.bars
                    WHERE instrument_id = 'ETHUSDT-SPOT.BYBIT'
                    AND ts_event = '2024-06-15 12:00:00+00'
                """)
                result = cur.fetchone()
                assert result is not None, "Timestamp not found"
                assert result[0].tzinfo is not None, "Timestamp should have timezone"

                # Clean up
                cur.execute("""
                    DELETE FROM raw_bybit.bars
                    WHERE instrument_id = 'ETHUSDT-SPOT.BYBIT'
                    AND ts_event = '2024-06-15 12:00:00+00'
                """)
                conn.commit()

        finally:
            conn.close()
