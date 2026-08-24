"""Shared fixtures for scanner tests."""

from datetime import datetime, UTC
from decimal import Decimal

import pytest

from app.setups.base import CandleData, IndicatorSnapshot


@pytest.fixture
def base_time():
    return datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)


@pytest.fixture
def make_candle(base_time):
    def _make(
        open_time: datetime | None = None,
        open_price: float = 100.0,
        high: float = 105.0,
        low: float = 95.0,
        close: float = 102.0,
        volume: float = 1000.0,
    ) -> CandleData:
        return CandleData(
            symbol="TESTUSDT",
            open_time=open_time or base_time,
            open=Decimal(str(open_price)),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
            volume=Decimal(str(volume)),
        )
    return _make


@pytest.fixture
def make_indicators():
    def _make(
        ema20: float | None = 100.0,
        ema50: float | None = 95.0,
        ema200: float | None = 90.0,
        atr: float | None = 2.0,
        volume_ma20: float | None = 1000.0,
    ) -> IndicatorSnapshot:
        return IndicatorSnapshot(
            ema20=Decimal(str(ema20)) if ema20 is not None else None,
            ema50=Decimal(str(ema50)) if ema50 is not None else None,
            ema200=Decimal(str(ema200)) if ema200 is not None else None,
            atr=Decimal(str(atr)) if atr is not None else None,
            volume_ma20=Decimal(str(volume_ma20)) if volume_ma20 is not None else None,
        )
    return _make
