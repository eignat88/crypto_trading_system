from pathlib import Path

SQL = (Path(__file__).parents[2] / "database" / "migrations" / "005_raw_to_dds_etl.sql").read_text()


def test_etl_seeds_supported_instruments_and_is_idempotent() -> None:
    assert "('bybit', 'BTCUSDT', 'BTC', 'USDT')" in SQL
    assert "('bybit', 'ETHUSDT', 'ETH', 'USDT')" in SQL
    assert "ON CONFLICT (instrument_id, interval_code, open_time) DO NOTHING" in SQL


def test_etl_separates_open_and_closed_candles() -> None:
    assert "close_time <= p_as_of" in SQL
    assert "close_time > p_as_of" in SQL
    assert "deferred_count" in SQL


def test_etl_has_quality_events_checkpoint_and_report() -> None:
    assert "dds.data_quality_event" in SQL
    assert "dds.etl_checkpoint" in SQL
    assert "dds.etl_run" in SQL
    for count in ("source_count", "inserted_count", "rejected_count"):
        assert count in SQL
