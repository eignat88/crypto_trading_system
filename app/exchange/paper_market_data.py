from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import datetime

from app.models.candle import Candle


class PaperMarketData:
    """Deterministic historical candle replay for paper trading.

    The component only publishes market data. It does not know about
    strategies, risk decisions or order execution.
    """

    def __init__(self, candles: Iterable[Candle]) -> None:
        self._candles = sorted(candles, key=lambda item: item.open_time)
        self._last_processed_time: datetime | None = None

    @property
    def last_processed_time(self) -> datetime | None:
        return self._last_processed_time

    def replay(self) -> Iterator[Candle]:
        for candle in self._candles:
            candle.validate()

            if self._last_processed_time is not None:
                if candle.open_time <= self._last_processed_time:
                    continue

            self._last_processed_time = candle.open_time
            yield candle
