import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.models.candle import Candle
from app.pipeline import MarketEvent, MarketPipeline, PipelineStatus


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.risks: list[str] = []

    async def save(self, event):
        self.calls.append("raw")

    async def normalize(self, event):
        self.calls.append("dds")
        return event.candle

    async def calculate(self, candle):
        self.calls.append("indicators")
        return {"EMA": 1, "RSI": 2, "ATR": 3}

    async def detect(self, candle, indicators):
        self.calls.append("regime")
        return "TREND_UP"

    async def evaluate(self, *args):
        self.calls.append("evaluate")
        return SimpleNamespace(symbol="BTCUSDT")

    async def execute(self, signal, sequence):
        self.calls.append("execute")
        return "fill"

    async def persist(self, *args):
        self.calls.append("persist")

    async def checkpoint(self, *args):
        self.calls.append("checkpoint")

    async def record(self, event, reason, detail):
        self.risks.append(reason)


def event(sequence: int) -> MarketEvent:
    end = datetime.now(UTC) - timedelta(minutes=1)
    return MarketEvent(
        Candle(
            "BTCUSDT",
            end - timedelta(hours=1),
            end,
            Decimal("10"),
            Decimal("11"),
            Decimal("9"),
            Decimal("10"),
            Decimal("2"),
        ),
        sequence,
    )


def test_full_flow_and_duplicate_guard() -> None:
    asyncio.run(_full_flow_and_duplicate_guard())


async def _full_flow_and_duplicate_guard() -> None:
    service = Recorder()
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
        required_candles=1,
    )
    # Risk uses the same evaluate test double and returns an object without approved.
    service.evaluate = lambda *args: SimpleNamespace(approved=True)
    first = await pipeline.process_market_event(event(100))
    second = await pipeline.process_market_event(event(100))
    assert first.status is PipelineStatus.PROCESSED
    assert first.trading_ready
    assert second.status is PipelineStatus.IGNORED
    assert service.calls.count("raw") == 1


def test_indicator_failure_degrades_and_records_risk_event() -> None:
    asyncio.run(_indicator_failure_degrades_and_records_risk_event())


async def _indicator_failure_degrades_and_records_risk_event() -> None:
    service = Recorder()

    async def fail(candle):
        raise RuntimeError("RSI calculation failed")

    service.calculate = fail
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
    )
    result = await pipeline.process_market_event(event(1))
    assert result.status is PipelineStatus.FAILED
    assert not result.trading_ready
    assert "RSI calculation failed" in service.risks[0]
