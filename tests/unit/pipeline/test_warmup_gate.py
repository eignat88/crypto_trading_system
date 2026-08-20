import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.models.candle import Candle
from app.pipeline import MarketEvent, MarketPipeline, PipelineStatus


class WarmupServices:
    def __init__(self):
        self.strategy_calls = 0

    async def save(self, event):
        pass

    async def normalize(self, event):
        return event.candle

    async def calculate(self, candle):
        return {"EMA": 1, "RSI": 2, "ATR": 3}

    async def detect(self, candle, indicators):
        return "SIDEWAYS"

    async def evaluate(self, *args):
        self.strategy_calls += 1

    async def execute(self, *args):
        raise AssertionError("execution must be gated")

    async def persist(self, *args):
        pass

    async def checkpoint(self, *args):
        pass

    async def record(self, *args):
        pass


def test_strategy_is_not_called_during_warmup() -> None:
    asyncio.run(_strategy_is_not_called_during_warmup())


async def _strategy_is_not_called_during_warmup() -> None:
    service = WarmupServices()
    pipeline = MarketPipeline(
        raw_store=service,
        dds_transformer=service,
        indicator_service=service,
        regime_service=service,
        strategy=service,
        risk_engine=service,
        execution_engine=service,
        persistence=service,
        risk_event_store=service,
        required_candles=2,
    )
    close = datetime.now(UTC) - timedelta(minutes=1)
    candle = Candle(
        "BTCUSDT",
        close - timedelta(hours=1),
        close,
        Decimal("1"),
        Decimal("1"),
        Decimal("1"),
        Decimal("1"),
        Decimal("1"),
    )
    result = await pipeline.process_market_event(MarketEvent(candle, 1))
    assert result.status is PipelineStatus.WARMUP
    assert service.strategy_calls == 0
