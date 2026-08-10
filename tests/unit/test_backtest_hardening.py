import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.backtest.slippage_model import SlippageModel
from app.indicators.market_regime import MarketRegime
from app.models import Fill
from app.strategies.trend_dca import TrendDCAStrategy


class RecordingSlippageModel:
    def __init__(self) -> None:
        self.average_volumes: list[Decimal | None] = []

    def calculate_slippage(
        self,
        price: Decimal,
        quantity: Decimal,
        average_volume: Decimal | None = None,
        is_buy: bool = True,
    ) -> Decimal:
        self.average_volumes.append(average_volume)
        return price


def _candle(
    timestamp: datetime,
    *,
    price: Decimal,
    volume: Decimal,
) -> dict:
    return {
        "open_time": timestamp,
        "symbol": "BTCUSDT",
        "open": price,
        "high": price,
        "low": price,
        "close": price,
        "volume": volume,
    }


def test_slippage_rng_does_not_mutate_process_global_random_state() -> None:
    random.seed(12345)
    expected = random.random()

    random.seed(12345)
    SlippageModel(seed=999)

    assert random.random() == expected


def test_engine_passes_only_completed_volume_to_slippage() -> None:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _candle(base_time, price=Decimal("100"), volume=Decimal("20")),
        _candle(
            base_time + timedelta(hours=1),
            price=Decimal("101"),
            volume=Decimal("999999"),
        ),
    ]
    engine = BacktestEngine(
        BacktestConfig(
            initial_balance=Decimal("5000"),
            end_position_policy="mark_to_market",
        )
    )
    recorder = RecordingSlippageModel()
    engine.slippage_model = recorder  # type: ignore[assignment]

    def strategy(candle, portfolio, state):
        if not portfolio.has_position("BTCUSDT"):
            return {
                "action": "buy",
                "symbol": "BTCUSDT",
                "quantity": Decimal("0.01"),
            }
        return None

    engine.run(candles, strategy)

    # The order is executed at candle 1 open. Its final volume is unavailable
    # at that moment, so only candle 0 volume may reach the slippage model.
    assert recorder.average_volumes[0] == Decimal("20")
    assert Decimal("999999") not in recorder.average_volumes


def test_mark_to_market_end_policy_preserves_open_position() -> None:
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _candle(base_time, price=Decimal("100"), volume=Decimal("1000")),
        _candle(
            base_time + timedelta(hours=1),
            price=Decimal("110"),
            volume=Decimal("1000"),
        ),
    ]
    engine = BacktestEngine(
        BacktestConfig(
            initial_balance=Decimal("5000"),
            end_position_policy="mark_to_market",
        )
    )

    def strategy(candle, portfolio, state):
        if not portfolio.has_position("BTCUSDT"):
            return {
                "action": "buy",
                "symbol": "BTCUSDT",
                "quantity": Decimal("0.01"),
            }
        return None

    result = engine.run(candles, strategy)

    assert result.total_trades == 0
    assert result.portfolio.has_position("BTCUSDT")
    assert len([fill for fill in result.fills if fill.side == "sell"]) == 0


def test_invalid_end_position_policy_fails_fast() -> None:
    with pytest.raises(ValueError, match="end_position_policy"):
        BacktestConfig(end_position_policy="unknown")


def test_trend_dca_entry_state_changes_only_after_fill() -> None:
    strategy = TrendDCAStrategy(["BTCUSDT"])
    strategy.dca_levels["BTCUSDT"] = 2
    strategy.trailing_highs["BTCUSDT"] = Decimal("120")
    now = datetime(2024, 1, 1, tzinfo=UTC)

    signal = strategy.should_enter(
        {
            "symbol": "BTCUSDT",
            "close": Decimal("105"),
            "open_time": now,
        },
        {
            "ema_200": Decimal("100"),
            "ema_50": Decimal("102"),
            "rsi": Decimal("40"),
            "regime": MarketRegime.TREND_UP,
            "volatility": Decimal("0.5"),
        },
        {
            "has_position": False,
            "capital": Decimal("5000"),
        },
    )

    assert signal is not None
    assert strategy.dca_levels["BTCUSDT"] == 2
    assert strategy.trailing_highs["BTCUSDT"] == Decimal("120")

    fill = Fill(
        fill_id="fill-1",
        order_id="order-1",
        symbol="BTCUSDT",
        side="buy",
        quantity=signal.quantity,
        price=signal.price,
        commission=Decimal("0"),
        timestamp=now,
    )
    strategy.on_fill(signal, fill)

    assert strategy.dca_levels["BTCUSDT"] == 0
    assert "BTCUSDT" not in strategy.trailing_highs
