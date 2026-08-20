from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.indicators.atr import calculate_atr
from app.indicators.ema import calculate_ema_series
from app.indicators.market_regime import MarketRegimeDetector
from app.indicators.rsi import calculate_rsi
from app.models.candle import Candle
from app.models.market_event import MarketEvent
from app.pipeline import MarketPipeline
from app.risk.risk_engine import RiskConfig, RiskEngine
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository


class RawStore:
    def __init__(self) -> None:
        self.events: list[MarketEvent] = []

    async def save(self, event: MarketEvent) -> None:
        self.events.append(event)


class DDSTransformer:
    def __init__(self) -> None:
        self.candles: list[Candle] = []

    async def normalize(self, event: MarketEvent) -> Candle:
        event.candle.validate()
        self.candles.append(event.candle)
        return event.candle


class ExistingIndicatorAdapter:
    """Incremental adapter using the application's production indicator functions."""

    def __init__(self) -> None:
        self.candles: list[Candle] = []
        self.rows: list[dict[str, Any]] = []

    async def calculate(self, candle: Candle) -> dict[str, Any]:
        self.candles.append(candle)
        closes = [row.close for row in self.candles]
        highs = [row.high for row in self.candles]
        lows = [row.low for row in self.candles]
        ema_50 = calculate_ema_series(closes, 50)[-1]
        ema_200 = calculate_ema_series(closes, 200)[-1]
        row = {
            "EMA": ema_200,
            "RSI": calculate_rsi(closes, 14),
            "ATR": calculate_atr(highs, lows, closes, 14),
            "ema_50": ema_50,
            "ema_200": ema_200,
            "rsi": calculate_rsi(closes, 14),
        }
        self.rows.append(row)
        return row


class ExistingRegimeAdapter:
    def __init__(self, indicators: ExistingIndicatorAdapter) -> None:
        self.indicators = indicators
        self.detector = MarketRegimeDetector()
        self.rows: list[Any] = []

    async def detect(self, candle: Candle, indicators: dict[str, Any]) -> Any:
        candles = self.indicators.candles
        result = self.detector.detect(
            [row.close for row in candles],
            [row.high for row in candles],
            [row.low for row in candles],
        )
        self.rows.append(result)
        return result


class ExistingStrategyAdapter:
    def __init__(self, execution: PaperExecutionEngine) -> None:
        self.execution = execution
        self.strategy = TrendDCAStrategy(["BTCUSDT"], DCAConfig(rsi_entry_threshold=Decimal("100")))
        self.evaluations = 0

    async def evaluate(self, candle: Candle, indicators: dict[str, Any], regime: Any) -> Any:
        self.evaluations += 1
        values = dict(indicators)
        values["regime"] = regime.regime
        values["volatility"] = regime.volatility
        return self.strategy.should_enter(
            {
                "symbol": candle.symbol,
                "open_time": candle.open_time,
                "close": candle.close,
            },
            values,
            {
                "has_position": candle.symbol in self.execution.positions,
                "capital": self.execution.cash_balance,
            },
        )


class ExistingRiskAdapter:
    def __init__(self, execution: PaperExecutionEngine) -> None:
        self.execution = execution
        self.engine = RiskEngine(RiskConfig())
        self.decisions = 0

    async def evaluate(self, signal: Any) -> Any:
        self.decisions += 1
        positions = {
            symbol: {
                "symbol": symbol,
                "value": position.quantity * position.average_price,
                "side": "buy",
            }
            for symbol, position in self.execution.positions.items()
        }
        return self.engine.check_trade(
            signal.symbol,
            "buy",
            signal.quantity,
            signal.price,
            self.execution.cash_balance,
            positions,
            Decimal("10000"),
            stop_loss_price=signal.stop_loss,
        )


class ExistingExecutionAdapter:
    def __init__(self, engine: PaperExecutionEngine, candles: DDSTransformer) -> None:
        self.engine = engine
        self.candles = candles
        self.results: list[Any] = []

    def on_market_event(self, event: MarketEvent) -> None:
        self.engine.on_market_event(event)

    async def execute(self, signal: Any, sequence: int) -> Any:
        result = self.engine.execute(
            ExecutionRequest(signal.symbol, OrderSide.BUY, signal.quantity),
            client_order_id=f"pipeline:{sequence}:{signal.symbol}",
        )
        self.results.append(result)
        return result


class DurablePersistence:
    def __init__(self, engine: PaperExecutionEngine) -> None:
        self.engine = engine
        self.events: list[tuple[Any, ...]] = []
        self.checkpoints: dict[str, int] = {}
        self.pnl = Decimal("0")

    async def persist(self, *values: Any) -> None:
        self.events.append(values)
        await self.engine.flush()

    async def checkpoint(self, symbol: str, sequence: int) -> None:
        await self.engine.flush()
        await self.engine._save_state()
        self.checkpoints[symbol] = sequence


class RiskEvents:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    async def record(self, event: MarketEvent, reason: str, detail: Any) -> None:
        self.events.append((reason, detail))


def candle_event(sequence: int) -> MarketEvent:
    start = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=sequence)
    price = Decimal("100") + Decimal(sequence)
    candle = Candle(
        "BTCUSDT",
        start,
        start + timedelta(hours=1),
        price - Decimal("1"),
        price + Decimal("1"),
        price - Decimal("2"),
        price,
        Decimal("10"),
    )
    return MarketEvent(candle, sequence, source="integration-exchange")


def build_pipeline(repository: MemoryCheckpointRepository, required: int = 200):
    engine = PaperExecutionEngine(state_repository=repository)  # type: ignore[arg-type]
    engine.cash_balance = Decimal("10000")
    raw = RawStore()
    dds = DDSTransformer()
    indicators = ExistingIndicatorAdapter()
    regimes = ExistingRegimeAdapter(indicators)
    strategy = ExistingStrategyAdapter(engine)
    risk = ExistingRiskAdapter(engine)
    execution = ExistingExecutionAdapter(engine, dds)
    persistence = DurablePersistence(engine)
    risk_events = RiskEvents()
    mart = SimpleNamespace(refreshes=0)

    async def refresh_mart() -> None:
        mart.refreshes += 1

    pipeline = MarketPipeline(
        raw_store=raw,
        dds_transformer=dds,
        indicator_service=indicators,
        regime_service=regimes,
        strategy=strategy,
        risk_engine=risk,
        execution_engine=execution,
        persistence=persistence,
        risk_event_store=risk_events,
        mart_refresh=refresh_mart,
        required_candles=required,
        symbols={"BTCUSDT"},
    )
    return SimpleNamespace(
        pipeline=pipeline,
        engine=engine,
        raw=raw,
        dds=dds,
        indicators=indicators,
        regimes=regimes,
        strategy=strategy,
        risk=risk,
        execution=execution,
        persistence=persistence,
        risk_events=risk_events,
        mart=mart,
    )
