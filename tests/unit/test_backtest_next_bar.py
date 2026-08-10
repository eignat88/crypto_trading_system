from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine


def _candle(
    timestamp: datetime,
    *,
    open_price: str,
    high: str,
    low: str,
    close: str,
) -> dict:
    return {
        "open_time": timestamp,
        "symbol": "BTCUSDT",
        "open": Decimal(open_price),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
        "volume": Decimal("1000"),
    }


def test_strategy_signal_executes_only_at_next_bar_open():
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _candle(
            base_time,
            open_price="100",
            high="112",
            low="99",
            close="110",
        ),
        _candle(
            base_time + timedelta(hours=1),
            open_price="120",
            high="121",
            low="119",
            close="120",
        ),
    ]

    def strategy(candle, portfolio, state):
        if candle["open_time"] == base_time:
            return {
                "action": "buy",
                "symbol": "BTCUSDT",
                "quantity": Decimal("1"),
                "price": candle["close"],
                "reason": "causal entry",
            }
        return None

    engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("5000")))
    result = engine.run(candles, strategy)

    buy_order = next(order for order in result.orders if order.side == "buy")
    buy_fill = next(fill for fill in result.fills if fill.side == "buy")
    entry_signal = next(signal for signal in result.signals if signal.reason == "causal entry")

    assert entry_signal.timestamp == base_time
    assert entry_signal.price == Decimal("110")
    assert buy_order.created_at == base_time + timedelta(hours=1)
    assert buy_order.requested_price == Decimal("120")
    assert buy_fill.timestamp == base_time + timedelta(hours=1)
    assert buy_fill.price > Decimal("120")


def test_final_candle_strategy_signal_remains_unfilled():
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _candle(
            base_time,
            open_price="100",
            high="101",
            low="99",
            close="100",
        )
    ]

    engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("5000")))
    result = engine.run(
        candles,
        lambda candle, portfolio, state: {
            "action": "buy",
            "symbol": "BTCUSDT",
            "quantity": Decimal("1"),
            "price": candle["close"],
            "reason": "last-bar signal",
        },
    )

    assert len(result.signals) == 1
    assert result.signals[0].reason == "last-bar signal"
    assert result.orders == []
    assert result.risk_decisions == []
    assert result.fills == []
    assert result.portfolio.positions == {}


def test_next_open_entry_can_hit_fixed_stop_on_same_execution_bar():
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    candles = [
        _candle(
            base_time,
            open_price="100",
            high="101",
            low="99",
            close="100",
        ),
        _candle(
            base_time + timedelta(hours=1),
            open_price="100",
            high="101",
            low="94",
            close="99",
        ),
    ]

    def strategy(candle, portfolio, state):
        if candle["open_time"] == base_time:
            return {
                "action": "buy",
                "symbol": "BTCUSDT",
                "quantity": Decimal("1"),
                "price": candle["close"],
                "stop_loss": Decimal("95"),
                "take_profit": Decimal("110"),
                "reason": "entry with stop",
            }
        return None

    engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("5000")))
    result = engine.run(candles, strategy)

    buy_fill = next(fill for fill in result.fills if fill.side == "buy")
    sell_order = next(order for order in result.orders if order.side == "sell")
    sell_fill = next(fill for fill in result.fills if fill.side == "sell")

    assert buy_fill.timestamp == base_time + timedelta(hours=1)
    assert sell_order.created_at == base_time + timedelta(hours=1)
    assert sell_order.requested_price == Decimal("95")
    assert sell_fill.timestamp == base_time + timedelta(hours=1)
    assert sell_fill.price < Decimal("95")
    assert result.total_trades == 1
