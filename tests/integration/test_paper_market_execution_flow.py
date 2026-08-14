from datetime import datetime, timedelta
from decimal import Decimal

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.exchange.paper_market_data import PaperMarketData
from app.models.candle import Candle


def test_market_data_execution_flow() -> None:
    start = datetime(2026, 1, 1)

    candles = [
        Candle(
            symbol="BTCUSDT",
            open_time=start,
            close_time=start + timedelta(hours=1),
            open=Decimal("60000"),
            high=Decimal("61000"),
            low=Decimal("59000"),
            close=Decimal("60500"),
            volume=Decimal("10"),
        )
    ]

    market_data = PaperMarketData(candles)
    engine = PaperExecutionEngine()

    for event in market_data.stream():
        engine.on_market_event(event)

    assert engine.last_candle is not None
    assert engine.last_candle.close == Decimal("60500")
    assert engine.last_sequence == 1
