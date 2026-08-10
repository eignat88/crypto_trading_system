from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.indicators.market_regime import MarketRegime
from app.models import Fill
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy
from app.strategies.trend_pullback_confirmation import (
    PARAMETERS_VERSION,
    TrendPullbackConfirmationStrategy,
)

UTC = timezone.utc
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


def _portfolio(has_position: bool = False) -> dict:
    return {
        "has_position": has_position,
        "capital": Decimal("500"),
        "available_balance": Decimal("500"),
    }


def _arm(strategy: TrendPullbackConfirmationStrategy, hour: int = 0) -> None:
    signal = strategy.should_enter(
        _candle(hour), _indicators(rsi="44"), _portfolio()
    )
    assert signal is None
    assert strategy.state[SYMBOL]["phase"] == "PULLBACK_ARMED"


def test_setup_arms_without_immediate_buy() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    setup = strategy.state[SYMBOL]["setup"]
    assert setup is not None
    assert setup["bars_since_setup"] == 0
    assert setup["setup_rsi"] == "44"


def test_strict_rsi_up_cross_and_close_above_ema20_confirms() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    signal = strategy.should_enter(
        _candle(1, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    )

    assert signal is not None
    assert signal.reason == "Trend pullback recovery confirmed"
    assert signal.parameters_version == PARAMETERS_VERSION
    assert signal.metadata["bars_since_setup"] == 1
    assert signal.metadata["setup_rsi"] == "44"
    assert signal.metadata["confirmation_rsi"] == "46"
    assert strategy.state[SYMBOL]["phase"] == "IDLE"
    assert strategy.state[SYMBOL]["setup"] is None


def test_rsi_at_or_below_45_does_not_confirm() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    assert strategy.should_enter(
        _candle(1), _indicators(rsi="45"), _portfolio()
    ) is None
    assert strategy.state[SYMBOL]["phase"] == "PULLBACK_ARMED"


def test_rsi_above_45_without_cross_does_not_confirm() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)
    strategy.should_enter(_candle(1), _indicators(rsi="46"), _portfolio())
    # Force a second armed setup to verify that previous RSI=46 prevents a
    # false cross even though current RSI remains above 45.
    strategy.state[SYMBOL]["phase"] = "PULLBACK_ARMED"
    strategy.state[SYMBOL]["setup"] = {
        "setup_time": _candle(1)["open_time"].isoformat(),
        "setup_rsi": "44",
        "setup_close": "105",
        "setup_ema20": "104",
        "setup_ema50": "102",
        "setup_ema200": "100",
        "setup_regime": str(MarketRegime.TREND_UP),
        "bars_since_setup": 0,
    }

    assert strategy.should_enter(
        _candle(2), _indicators(rsi="47"), _portfolio()
    ) is None


def test_close_at_or_below_ema20_does_not_confirm() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    assert strategy.should_enter(
        _candle(1, "104"), _indicators(rsi="46", ema20="104"), _portfolio()
    ) is None
    assert strategy.state[SYMBOL]["phase"] == "PULLBACK_ARMED"


def test_regime_change_cancels_setup() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    assert strategy.should_enter(
        _candle(1),
        _indicators(rsi="46", regime=MarketRegime.RANGE),
        _portfolio(),
    ) is None
    assert strategy.state[SYMBOL]["phase"] == "IDLE"


def test_close_at_or_below_ema200_cancels_setup() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    assert strategy.should_enter(
        _candle(1, "100"), _indicators(rsi="46", ema20="99", ema200="100"), _portfolio()
    ) is None
    assert strategy.state[SYMBOL]["phase"] == "IDLE"


def test_ema50_at_or_below_ema200_cancels_setup() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    assert strategy.should_enter(
        _candle(1), _indicators(rsi="46", ema50="100", ema200="100"), _portfolio()
    ) is None
    assert strategy.state[SYMBOL]["phase"] == "IDLE"


def test_timeout_at_12_bars_cancels_before_confirmation() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    for hour in range(1, 12):
        assert strategy.should_enter(
            _candle(hour), _indicators(rsi="44"), _portfolio()
        ) is None
        assert strategy.state[SYMBOL]["phase"] == "PULLBACK_ARMED"

    # On the 12th completed candle, even a valid cross is too late.
    assert strategy.should_enter(
        _candle(12, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    ) is None
    assert strategy.state[SYMBOL]["phase"] == "IDLE"


def test_repeated_setup_candles_do_not_reset_timeout() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)

    for hour in range(1, 5):
        strategy.should_enter(_candle(hour), _indicators(rsi="43"), _portfolio())

    setup = strategy.state[SYMBOL]["setup"]
    assert setup is not None
    assert setup["bars_since_setup"] == 4
    assert setup["setup_time"] == START.isoformat()


def test_signal_does_not_advance_dca_state_until_fill() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(1, "106"), _indicators(rsi="46", ema20="105"), _portfolio()
    )
    assert signal is not None
    assert SYMBOL not in strategy.dca_levels

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
    assert strategy.dca_levels[SYMBOL] == 0


def test_dca_behavior_matches_baseline_for_equivalent_position() -> None:
    baseline = TrendDCAStrategy([SYMBOL], DCAConfig())
    v2 = TrendPullbackConfirmationStrategy([SYMBOL])
    baseline.dca_levels[SYMBOL] = 0
    v2.dca_levels[SYMBOL] = 0

    candle = _candle(5, "96")
    indicators = _indicators(rsi="40")
    position = {
        "entry_price": Decimal("100"),
        "quantity": Decimal("0.1"),
        "capital": Decimal("500"),
        "holding_periods": 10,
        "unrealized_pnl_pct": Decimal("-0.04"),
    }

    assert baseline.should_add_dca(candle, indicators, position) == v2.should_add_dca(
        candle, indicators, position
    )


def test_exit_behavior_matches_baseline_for_equivalent_position() -> None:
    baseline = TrendDCAStrategy([SYMBOL], DCAConfig())
    v2 = TrendPullbackConfirmationStrategy([SYMBOL])
    candle = _candle(5, "98")
    indicators = _indicators(rsi="50", regime=MarketRegime.TREND_DOWN)
    position = {
        "entry_price": Decimal("100"),
        "quantity": Decimal("0.1"),
        "holding_periods": 10,
        "unrealized_pnl_pct": Decimal("-0.02"),
    }

    assert baseline.should_exit(candle, indicators, position) == v2.should_exit(
        candle, indicators, position
    )


def test_final_candle_confirmation_produces_signal_but_no_fill() -> None:
    strategy = TrendPullbackConfirmationStrategy([SYMBOL])
    candles = [
        {**_candle(0), "indicators": _indicators(rsi="44")},
        {**_candle(1, "106"), "indicators": _indicators(rsi="46", ema20="105")},
    ]
    engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("500"), random_seed=42))

    result = engine.run(
        candles=candles,
        strategy=strategy,
        indicator_provider=lambda candle, index: candle["indicators"],
    )

    assert len(result.signals) == 1
    assert result.signals[0].reason == "Trend pullback recovery confirmed"
    assert len(result.orders) == 0
    assert len(result.fills) == 0
    assert result.total_trades == 0
