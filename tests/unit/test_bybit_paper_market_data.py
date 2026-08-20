import asyncio
from datetime import UTC, datetime, timedelta

from app.exchange.bybit_paper_market_data import BybitPaperMarketData


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(self, query, *args):
        return self.rows


class NoBackfillCollector:
    async def load_historical_candles(self, *args, **kwargs):
        raise AssertionError("sufficient history must not trigger a backfill")


def test_bootstrap_accepts_complete_fresh_closed_history() -> None:
    boundary = BybitPaperMarketData._latest_closed_boundary(datetime.now(UTC))
    rows = [
        {
            "symbol": symbol,
            "candle_count": 250,
            "first_candle": boundary - timedelta(hours=250),
            "last_candle": boundary - timedelta(hours=1),
            "last_close": boundary,
            "duplicate_count": 0,
            "gap_count": 0,
        }
        for symbol in ("BTCUSDT", "ETHUSDT")
    ]
    source = BybitPaperMarketData(
        connection=FakeConnection(rows),  # type: ignore[arg-type]
        collector=NoBackfillCollector(),  # type: ignore[arg-type]
        symbols=["BTCUSDT", "ETHUSDT"],
        interval="1h",
        warmup_candles=200,
        backfill_buffer=50,
        poll_seconds=60,
        stale_grace_seconds=600,
    )

    assert asyncio.run(source.bootstrap()) == {"BTCUSDT": 250, "ETHUSDT": 250}
    assert source.ready is True
    assert source._last_emitted == {
        "BTCUSDT": boundary - timedelta(hours=1),
        "ETHUSDT": boundary - timedelta(hours=1),
    }


def test_latest_boundary_excludes_open_hour() -> None:
    now = datetime(2026, 8, 20, 17, 10, tzinfo=UTC)
    assert BybitPaperMarketData._latest_closed_boundary(now) == datetime(
        2026, 8, 20, 17, tzinfo=UTC
    )


def test_restore_boundary_skips_only_durably_processed_symbol_events() -> None:
    source = BybitPaperMarketData(
        connection=FakeConnection([]),  # type: ignore[arg-type]
        collector=NoBackfillCollector(),  # type: ignore[arg-type]
        symbols=["BTCUSDT", "ETHUSDT"],
        interval="1h",
        warmup_candles=200,
        backfill_buffer=50,
        poll_seconds=60,
        stale_grace_seconds=600,
    )
    opened = datetime(2026, 8, 20, 17, tzinfo=UTC)
    btc_sequence = int(opened.timestamp()) * 10

    source.restore_boundary(btc_sequence, opened)

    assert source._last_emitted["BTCUSDT"] == opened
    assert source._last_emitted["ETHUSDT"] == opened - timedelta(hours=1)
