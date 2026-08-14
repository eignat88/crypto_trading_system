from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import (
    ExecutionRequest,
    OrderSide,
    PaperExecutionEngine,
)
from app.exchange.paper_market_data import PaperMarketData
from app.models.candle import Candle


def make_candle(open_time: datetime, close: Decimal) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        open_time=open_time,
        close_time=open_time + timedelta(hours=1),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1"),
    )


def test_cutoff_does_not_allow_future_candle_processing() -> None:
    start = datetime(2026, 1, 1)
    market_data = PaperMarketData(
        [
            make_candle(start, Decimal("60000")),
            make_candle(start + timedelta(hours=1), Decimal("61000")),
        ]
    )

    engine = PaperExecutionEngine()

    first_event = next(market_data.stream())
    engine.on_market_event(first_event)

    assert engine.last_candle is not None
    assert engine.last_candle.close == Decimal("60000")
    assert engine.last_sequence == 1


def test_warmup_without_market_data_blocks_execution() -> None:
    engine = PaperExecutionEngine()

    with pytest.raises(RuntimeError):
        engine.execute(
            ExecutionRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.1"),
            )
        )
