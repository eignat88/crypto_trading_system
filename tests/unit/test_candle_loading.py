from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.collectors.candle_collector import CandleCollector, interval_duration
from app.exchange.base_exchange import Candle


def candle(open_time: datetime) -> Candle:
    return Candle(
        exchange_name="bybit",
        symbol="BTCUSDT",
        interval_code="5m",
        open_time=open_time,
        close_time=None,
        open_price=Decimal("1"),
        high_price=Decimal("1"),
        low_price=Decimal("1"),
        close_price=Decimal("1"),
        volume=Decimal("1"),
        quote_volume=Decimal("1"),
        trade_count=None,
    )


def test_interval_duration_uses_full_timeframe() -> None:
    assert interval_duration("5m") == timedelta(minutes=5)
    assert interval_duration("1d") == timedelta(days=1)


@pytest.mark.parametrize("offsets", [[0, 0], [0, 10]])
def test_batch_validation_rejects_duplicates_and_gaps(offsets: list[int]) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    candles = [candle(start + timedelta(minutes=offset)) for offset in offsets]

    with pytest.raises(ValueError):
        CandleCollector._validate_batch(candles, timedelta(minutes=5), None)


def test_batch_validation_rejects_gap_between_pages() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="between"):
        CandleCollector._validate_batch(
            [candle(start + timedelta(minutes=15))], timedelta(minutes=5), start
        )
