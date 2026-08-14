from datetime import UTC, datetime
from decimal import Decimal

from app.exchange.paper_market_data import PaperMarketData
from app.models.candle import Candle


def make_candle(hour: int) -> Candle:
    start = datetime(2026, 8, 14, hour, tzinfo=UTC)
    return Candle(
        symbol="BTCUSDT",
        open_time=start,
        close_time=start.replace(minute=59),
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1"),
    )


def test_replay_is_deterministic() -> None:
    feed = PaperMarketData([make_candle(2), make_candle(1)])

    result = list(feed.replay())

    assert result[0].open_time.hour == 1
    assert result[1].open_time.hour == 2


def test_replay_does_not_duplicate_processed_candles() -> None:
    feed = PaperMarketData([make_candle(1)])

    assert len(list(feed.replay())) == 1
    assert len(list(feed.replay())) == 0
