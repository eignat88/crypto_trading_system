"""Unit tests for indicator collection and idempotency."""

from pathlib import Path

SQL = (Path(__file__).parents[2] / "sql" / "006_dds_to_mart_etl.sql").read_text()


def test_mart_etl_creates_daily_ohlcv_table() -> None:
    """Test that MART ETL creates daily OHLCV table."""
    assert "CREATE TABLE IF NOT EXISTS mart.daily_ohlcv" in SQL
    assert "report_date" in SQL
    assert "exchange_name" in SQL
    assert "symbol" in SQL
    assert "open_price" in SQL
    assert "high_price" in SQL
    assert "low_price" in SQL
    assert "close_price" in SQL
    assert "total_volume" in SQL


def test_mart_etl_is_idempotent() -> None:
    """Test that MART ETL uses ON CONFLICT for idempotency."""
    assert "ON CONFLICT (report_date, exchange_name, symbol)" in SQL
    assert "DO UPDATE SET" in SQL


def test_mart_etl_has_run_log() -> None:
    """Test that MART ETL has execution logging."""
    assert "CREATE TABLE IF NOT EXISTS mart.etl_run" in SQL
    assert "run_id" in SQL
    assert "rows_processed" in SQL
    assert "status" in SQL
    assert "started_at" in SQL
    assert "completed_at" in SQL


def test_mart_etl_has_refresh_function() -> None:
    """Test that MART ETL defines refresh function."""
    assert "CREATE OR REPLACE FUNCTION mart.refresh_daily_ohlcv" in SQL
    assert "p_target_date" in SQL


def test_mart_etl_strategy_performance_placeholder() -> None:
    """Test that strategy performance table exists as placeholder."""
    assert "CREATE TABLE IF NOT EXISTS mart.strategy_performance" in SQL
    assert "strategy_name" in SQL
    assert "trades_count" in SQL


def test_mart_etl_uses_first_last_aggregation() -> None:
    """Test that daily aggregation uses FIRST/LAST for OHLC."""
    assert "FIRST(c.open_price ORDER BY c.open_time)" in SQL
    assert "LAST(c.close_price ORDER BY c.open_time)" in SQL
    assert "MAX(c.high_price)" in SQL
    assert "MIN(c.low_price)" in SQL
    assert "SUM(c.volume)" in SQL


def test_mart_etl_filters_valid_candles() -> None:
    """Test that ETL only processes valid candles."""
    assert "c.is_valid = true" in SQL


def test_mart_etl_joins_instrument() -> None:
    """Test that ETL joins with instrument table."""
    assert "JOIN dds.instrument i ON c.instrument_id = i.instrument_id" in SQL
