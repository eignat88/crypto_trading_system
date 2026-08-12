from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.indicators.market_regime import MarketRegime
from app.models import Fill
from app.strategies.breakout_retest import (
    PARAMETERS_VERSION,
    RESISTANCE_LOOKBACK_BARS,
    RETEST_TIMEOUT_BARS,
    BreakoutRetestConfig,
    BreakoutRetestStrategy,
)

UTC = timezone.utc
START = datetime(2026, 1, 1, tzinfo=UTC)
BTC = "BTCUSDT"
ETH = "ETHUSDT"


def _candle(
    hour: int,
    *,
    symbol: str = BTC,
    open_: str | None = None,
    high: str = "105",
    low: str = "103",
    close: str = "104",
) -> dict:
    return {
        "symbol": symbol,
        "open_time": START + timedelta(hours=hour),
        "open": Decimal(open_ or close),
        "high": Decimal(high),
        "low": Decimal(low),
        "close": Decimal(close),
    }


def _indicators(
    *,
    ema50: str = "102",
    ema200: str = "100",
    regime=MarketRegime.TREND_UP,
    volatility: str | None = "0.10",
) -> dict:
    return {
        "ema_20": Decimal("103"),
        "ema_50": Decimal(ema50),
        "ema_200": Decimal(ema200),
        "rsi": Decimal("50"),
        "regime": regime,
        "volatility": None if volatility is None else Decimal(volatility),
    }


def _portfolio(has_position: bool = False, capital: str = "500") -> dict:
    return {
        "has_position": has_position,
        "capital": Decimal(capital),
        "available_balance": Decimal(capital),
    }


def _warmup(strategy: BreakoutRetestStrategy, *, symbol: str = BTC) -> None:
    for hour in range(RESISTANCE_LOOKBACK_BARS):
        high = str(100 + hour)
        candle = _candle(hour, symbol=symbol, high=high, low="90", close="95")
        assert strategy.should_enter(candle, _indicators(), _portfolio()) is None


def _arm(strategy: BreakoutRetestStrategy, *, symbol: str = BTC, hour: int = 20) -> None:
    _warmup(strategy, symbol=symbol)
    signal = strategy.should_enter(
        _candle(hour, symbol=symbol, high="200", low="118", close="120"),
        _indicators(regime=MarketRegime.RANGE),
        _portfolio(),
    )
    assert signal is None
    assert strategy.state[symbol]["phase"] == "BREAKOUT_ARMED"
    assert strategy.state[symbol]["breakout"]["breakout_level"] == "119"


def test_01_resistance_excludes_current_candle_high() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _warmup(strategy)
    resistance = strategy._observe_candle(
        _candle(20, high="999", low="118", close="120")
    )
    assert resistance == Decimal("119")


def test_02_resistance_uses_exactly_last_20_completed_candles() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    strategy._observe_candle(_candle(0, high="999", close="90"))
    for hour in range(1, 21):
        strategy._observe_candle(_candle(hour, high=str(100 + hour), close="90"))
    resistance = strategy._observe_candle(_candle(21, high="500", close="90"))
    assert resistance == Decimal("120")


def test_03_fewer_than_20_prior_candles_cannot_break_out() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    for hour in range(19):
        strategy.should_enter(
            _candle(hour, high="100", close="150"), _indicators(), _portfolio()
        )
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_04_close_equal_resistance_is_not_breakout() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _warmup(strategy)
    strategy.should_enter(
        _candle(20, high="130", low="118", close="119"),
        _indicators(),
        _portfolio(),
    )
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_05_breakout_arms_without_immediate_buy_and_allows_range_regime() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    breakout = strategy.state[BTC]["breakout"]
    assert breakout["bars_since_breakout"] == 0
    assert breakout["breakout_close"] == "120"
    assert breakout["breakout_regime"] == str(MarketRegime.RANGE)


def test_06_breakout_candle_cannot_self_retest() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _warmup(strategy)
    signal = strategy.should_enter(
        _candle(20, high="125", low="110", close="120"),
        _indicators(),
        _portfolio(),
    )
    assert signal is None
    assert strategy.state[BTC]["phase"] == "BREAKOUT_ARMED"


def test_07_valid_later_retest_hold_emits_buy_signal() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(21, high="122", low="118", close="119"),
        _indicators(),
        _portfolio(),
    )
    assert signal is not None
    assert signal.reason == "Breakout retest held"
    assert signal.parameters_version == PARAMETERS_VERSION
    assert signal.metadata["breakout_level"] == "119"
    assert signal.metadata["bars_since_breakout"] == 1
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_08_touch_but_close_below_breakout_level_does_not_confirm() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(21, high="120", low="117", close="118"),
        _indicators(),
        _portfolio(),
    )
    assert signal is None
    assert strategy.state[BTC]["phase"] == "BREAKOUT_ARMED"


def test_09_retest_requires_context_and_volatility_gate() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(21, high="120", low="118", close="119"),
        _indicators(volatility="0.81"),
        _portfolio(),
    )
    assert signal is None
    assert strategy.state[BTC]["phase"] == "BREAKOUT_ARMED"


def test_10_regime_trend_down_cancels_before_retest() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(21, high="120", low="118", close="119"),
        _indicators(regime=MarketRegime.TREND_DOWN),
        _portfolio(),
    )
    assert signal is None
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_11_close_at_or_below_ema200_cancels_before_retest() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    strategy.should_enter(
        _candle(21, high="120", low="99", close="100"),
        _indicators(ema200="100"),
        _portfolio(),
    )
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_12_ema50_at_or_below_ema200_cancels_before_retest() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    strategy.should_enter(
        _candle(21, high="120", low="118", close="119"),
        _indicators(ema50="100", ema200="100"),
        _portfolio(),
    )
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_13_open_position_cancels_armed_setup() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    strategy.should_enter(
        _candle(21, high="120", low="118", close="119"),
        _indicators(),
        _portfolio(has_position=True),
    )
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_14_timeout_at_24th_completed_candle_cancels_before_valid_retest() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    for offset in range(1, RETEST_TIMEOUT_BARS):
        signal = strategy.should_enter(
            _candle(20 + offset, high="125", low="121", close="122"),
            _indicators(),
            _portfolio(),
        )
        assert signal is None
        assert strategy.state[BTC]["phase"] == "BREAKOUT_ARMED"
    signal = strategy.should_enter(
        _candle(20 + RETEST_TIMEOUT_BARS, high="120", low="118", close="119"),
        _indicators(),
        _portfolio(),
    )
    assert signal is None
    assert strategy.state[BTC]["phase"] == "IDLE"


def test_15_higher_resistance_while_armed_does_not_replace_breakout_level() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    for hour in range(21, 25):
        strategy.should_enter(
            _candle(hour, high="300", low="121", close="250"),
            _indicators(),
            _portfolio(),
        )
    assert strategy.state[BTC]["breakout"]["breakout_level"] == "119"


def test_16_dca_is_disabled() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    assert strategy.should_add_dca(
        _candle(30, close="90"),
        _indicators(),
        {
            "entry_price": Decimal("100"),
            "quantity": Decimal("0.1"),
            "capital": Decimal("500"),
            "unrealized_pnl_pct": Decimal("-0.10"),
        },
    ) is None


def test_17_position_sizing_and_exit_parameters_match_frozen_values() -> None:
    strategy = BreakoutRetestStrategy([BTC])
    _arm(strategy)
    signal = strategy.should_enter(
        _candle(21, high="122", low="118", close="119"),
        _indicators(),
        _portfolio(capital="500"),
    )
    assert signal is not None
    expected_value = Decimal("500") * Decimal("0.10") * Decimal("0.25")
    assert signal.quantity == expected_value / Decimal("119")
    assert signal.stop_loss == Decimal("119") * Decimal("0.85")
    assert signal.take_profit == Decimal("119") * Decimal("1.05")


def test_18_state_is_isolated_between_btc_and_eth() -> None:
    strategy = BreakoutRetestStrategy([BTC, ETH])
    _warmup(strategy, symbol=BTC)
    strategy.should_enter(
        _candle(20, symbol=BTC, high="200", low="118", close="120"),
        _indicators(),
        _portfolio(),
    )
    assert strategy.state[BTC]["phase"] == "BREAKOUT_ARMED"
    assert strategy.state[ETH]["phase"] == "IDLE"
    assert strategy.state[ETH]["recent_highs"] == []


def _causal_sequence() -> list[dict]:
    candles = []
    for hour in range(20):
        candles.append(
            {
                **_candle(hour, high=str(100 + hour), low="90", close="95"),
                "indicators": _indicators(),
            }
        )
    candles.append(
        {
            **_candle(20, open_="120", high="125", low="120", close="120"),
            "indicators": _indicators(),
        }
    )
    candles.append(
        {
            **_candle(21, open_="121", high="122", low="118", close="119"),
            "indicators": _indicators(),
        }
    )
    return candles


def test_19_final_candle_retest_signal_has_no_fill_without_next_open() -> None:
    engine = BacktestEngine(
        BacktestConfig(initial_balance=Decimal("500"), random_seed=42)
    )
    result = engine.run(
        candles=_causal_sequence(),
        strategy=BreakoutRetestStrategy([BTC]),
        indicator_provider=lambda candle, index: candle["indicators"],
    )
    assert len(result.signals) == 1
    assert result.signals[0].reason == "Breakout retest held"
    assert len(result.orders) == 0
    assert len(result.fills) == 0
    assert result.total_trades == 0


def test_20_repeated_backtest_is_deterministic_and_executes_on_n_plus_one_open() -> None:
    candles = _causal_sequence()
    candles.append(
        {
            **_candle(22, open_="120", high="121", low="120", close="120"),
            "indicators": _indicators(),
        }
    )
    results = []
    for _ in range(2):
        engine = BacktestEngine(
            BacktestConfig(initial_balance=Decimal("500"), random_seed=42)
        )
        results.append(
            engine.run(
                candles=candles,
                strategy=BreakoutRetestStrategy([BTC]),
                indicator_provider=lambda candle, index: candle["indicators"],
            )
        )
    first, second = results
    assert first.total_pnl == second.total_pnl
    assert first.total_trades == second.total_trades
    assert len(first.orders) == len(second.orders) == 2  # entry + EOB liquidation
    assert first.fills[0].timestamp == candles[22]["open_time"]
