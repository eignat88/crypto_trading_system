from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.indicators.market_regime import MarketRegime
from app.models import Fill
from app.reporting.v2_entry_funnel import (
    InstrumentedTrendPullbackConfirmation,
    _reconstruct_trades,
    _status_for_baseline_entry,
)
from app.strategies.trend_pullback_confirmation import TrendPullbackConfirmationStrategy

UTC = UTC
SYMBOL = "BTCUSDT"
START = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(hour: int, close: str = "105") -> dict:
    price = Decimal(close)
    return {
        "symbol": SYMBOL,
        "open_time": START + timedelta(hours=hour),
        "open": price,
        "high": price,
        "low": price,
        "close": price,
    }


def _indicators(
    *,
    rsi: str,
    ema20: str = "104",
    ema50: str = "102",
    ema200: str = "100",
    regime=MarketRegime.TREND_UP,
    volatility: str | None = "0.10",
) -> dict:
    return {
        "ema_20": Decimal(ema20),
        "ema_50": Decimal(ema50),
        "ema_200": Decimal(ema200),
        "rsi": Decimal(rsi),
        "regime": regime,
        "volatility": None if volatility is None else Decimal(volatility),
    }


def _portfolio() -> dict:
    return {
        "has_position": False,
        "capital": Decimal("500"),
        "available_balance": Decimal("500"),
    }


def _arm(strategy, hour: int = 0) -> None:
    assert strategy.should_enter(
        _candle(hour), _indicators(rsi="44"), _portfolio()
    ) is None


def test_instrumented_strategy_preserves_parent_confirmation_signal() -> None:
    parent = TrendPullbackConfirmationStrategy([SYMBOL])
    observed = InstrumentedTrendPullbackConfirmation([SYMBOL])
    _arm(parent)
    _arm(observed)

    parent_signal = parent.should_enter(
        _candle(1, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    )
    observed_signal = observed.should_enter(
        _candle(1, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    )

    assert parent_signal == observed_signal
    assert observed.traces[-1].event == "CONFIRMED"
    assert observed.lifecycles[-1].terminal_reason == "CONFIRMED"


def test_regime_cancellation_reason_matches_frozen_precedence() -> None:
    strategy = InstrumentedTrendPullbackConfirmation([SYMBOL])
    _arm(strategy)

    assert strategy.should_enter(
        _candle(1, "99"),
        _indicators(
            rsi="46",
            ema20="98",
            ema50="99",
            ema200="100",
            regime=MarketRegime.RANGE,
        ),
        _portfolio(),
    ) is None

    assert strategy.traces[-1].event == "CANCEL_REGIME"
    assert strategy.lifecycles[-1].terminal_reason == "CANCEL_REGIME"


def test_timeout_is_recorded_at_exact_twelfth_completed_bar() -> None:
    strategy = InstrumentedTrendPullbackConfirmation([SYMBOL])
    _arm(strategy)

    for hour in range(1, 12):
        strategy.should_enter(_candle(hour), _indicators(rsi="44"), _portfolio())
    strategy.should_enter(
        _candle(12, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    )

    assert strategy.traces[-1].event == "CANCEL_TIMEOUT"
    assert strategy.lifecycles[-1].bars_since_setup == 12


def test_rsi_cross_below_ema20_is_visible_but_does_not_signal() -> None:
    strategy = InstrumentedTrendPullbackConfirmation([SYMBOL])
    _arm(strategy)

    signal = strategy.should_enter(
        _candle(1, "103"), _indicators(rsi="46", ema20="104"), _portfolio()
    )

    assert signal is None
    trace = strategy.traces[-1]
    assert trace.event == "RSI_CROSS_NO_EMA20"
    assert trace.rsi_crossed_up is True
    assert trace.close_above_ema20 is False
    assert trace.signal_emitted is False


def test_confirmed_fill_counter_advances_only_on_buy_fill() -> None:
    strategy = InstrumentedTrendPullbackConfirmation([SYMBOL])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(1, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    )
    assert signal is not None
    assert strategy.base_fill_count == 0

    fill = Fill(
        fill_id="f1",
        order_id="o1",
        symbol=SYMBOL,
        side="buy",
        quantity=signal.quantity,
        price=signal.price,
        commission=Decimal("0.01"),
        timestamp=_candle(2)["open_time"],
    )
    strategy.on_fill(signal, fill)
    assert strategy.base_fill_count == 1


def test_reconstructed_trade_count_and_pnl_match_engine() -> None:
    strategy = InstrumentedTrendPullbackConfirmation([SYMBOL])
    candles = [
        {**_candle(0), "indicators": _indicators(rsi="44")},
        {**_candle(1, "106"), "indicators": _indicators(rsi="46", ema20="105")},
        {**_candle(2, "106"), "indicators": _indicators(rsi="50")},
        {
            **_candle(3, "104"),
            "indicators": _indicators(rsi="50", regime=MarketRegime.TREND_DOWN),
        },
        {**_candle(4, "104"), "indicators": _indicators(rsi="50")},
    ]
    engine = BacktestEngine(
        BacktestConfig(initial_balance=Decimal("500"), random_seed=42)
    )
    result = engine.run(
        candles=candles,
        strategy=strategy,
        indicator_provider=lambda candle, index: candle["indicators"],
    )

    trades = _reconstruct_trades(result)
    assert len(trades) == result.total_trades == 1
    assert sum((trade.pnl for trade in trades), Decimal("0")) == result.total_pnl
    assert trades[0].exit_reason == "Regime changed to TREND_DOWN"


def test_baseline_status_prefers_same_candle_trace() -> None:
    strategy = InstrumentedTrendPullbackConfirmation([SYMBOL])
    _arm(strategy)
    strategy.should_enter(_candle(1), _indicators(rsi="44"), _portfolio())
    trace = strategy.traces[-1]

    status = _status_for_baseline_entry(
        trace.timestamp,
        {trace.timestamp: trace},
        [(START, START + timedelta(hours=10))],
    )
    assert status == "WAITING"


def test_baseline_status_identifies_open_v2_position_without_entry_trace() -> None:
    timestamp = START + timedelta(hours=5)
    status = _status_for_baseline_entry(
        timestamp,
        {},
        [(START + timedelta(hours=2), START + timedelta(hours=8))],
    )
    assert status == "V2_POSITION_OPEN"
