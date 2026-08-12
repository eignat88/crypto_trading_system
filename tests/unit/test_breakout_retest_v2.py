from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.indicators.market_regime import MarketRegime
from app.models import Fill, Signal
from app.strategies.breakout_retest import BreakoutRetestStrategy
from app.strategies.breakout_retest_v2 import (
    BreakoutRetestV2Config,
    BreakoutRetestV2Strategy,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SYMBOL = "BTCUSDT"


def _entry_signal(*, breakout_level: Decimal = Decimal("100")) -> Signal:
    return Signal(
        action="open_long",
        symbol=SYMBOL,
        price=Decimal("101"),
        quantity=Decimal("1"),
        timestamp=T0 - timedelta(hours=1),
        reason="Breakout retest held",
        strategy="BreakoutRetestV2",
        parameters_version="breakout_retest_v2",
        metadata={"breakout_level": str(breakout_level)},
    )


def _fill(*, side: str = "buy", price: Decimal = Decimal("101"), when: datetime = T0) -> Fill:
    return Fill(
        fill_id="fill-1",
        order_id="order-1",
        symbol=SYMBOL,
        side=side,
        quantity=Decimal("1"),
        price=price,
        commission=Decimal("0.1"),
        timestamp=when,
    )


def _candle(hour: int, *, close: Decimal = Decimal("101")) -> dict:
    return {
        "symbol": SYMBOL,
        "open_time": T0 + timedelta(hours=hour),
        "open": close,
        "high": close + Decimal("0.5"),
        "low": close - Decimal("0.5"),
        "close": close,
    }


def _indicators(
    *,
    ema20: Decimal = Decimal("100"),
    ema50: Decimal = Decimal("99"),
    regime: MarketRegime = MarketRegime.TREND_UP,
) -> dict:
    return {
        "ema_20": ema20,
        "ema_50": ema50,
        "ema_200": Decimal("90"),
        "regime": regime,
        "volatility": Decimal("0.1"),
    }


def _position(*, holding_periods: int = 1) -> dict:
    return {
        "symbol": SYMBOL,
        "side": "long",
        "entry_price": Decimal("101"),
        "quantity": Decimal("1"),
        "unrealized_pnl_pct": Decimal("-0.01"),
        "holding_periods": holding_periods,
        "capital": Decimal("500"),
        "high_water_mark": Decimal("101"),
    }


def _strategy() -> BreakoutRetestV2Strategy:
    strategy = BreakoutRetestV2Strategy([SYMBOL])
    strategy.on_fill(_entry_signal(), _fill())
    return strategy


def _advance_healthy(strategy: BreakoutRetestV2Strategy, through_hour: int) -> None:
    for hour in range(through_hour + 1):
        assert strategy.should_exit(
            _candle(hour, close=Decimal("101")),
            _indicators(),
            _position(holding_periods=hour + 1),
        ) is None


def _start_watch(strategy: BreakoutRetestV2Strategy) -> None:
    _advance_healthy(strategy, 22)
    result = strategy.should_exit(
        _candle(23, close=Decimal("98")),
        _indicators(ema20=Decimal("100"), ema50=Decimal("99")),
        _position(holding_periods=24),
    )
    assert result is None
    state = strategy.state[SYMBOL]
    assert state["position_state"] == "FAILURE_WATCH"
    assert state["failure_watch_bars"] == 0


def test_v1_strategy_remains_separate_and_unchanged() -> None:
    v1 = BreakoutRetestStrategy([SYMBOL])
    v2 = BreakoutRetestV2Strategy([SYMBOL])
    assert v1.config.parameters_version == "breakout_retest_v1"
    assert v2.config.parameters_version == "breakout_retest_v2"
    assert "position_state" not in v1.state[SYMBOL]
    assert v2.state[SYMBOL]["position_state"] is None


def test_v2_configuration_is_frozen() -> None:
    with pytest.raises(ValueError, match="failure_detection_age_bars is frozen"):
        BreakoutRetestV2Strategy(
            [SYMBOL],
            BreakoutRetestV2Config(failure_detection_age_bars=23),
        )
    with pytest.raises(ValueError, match="failure_watch_max_bars is frozen"):
        BreakoutRetestV2Strategy(
            [SYMBOL],
            BreakoutRetestV2Config(failure_watch_max_bars=12),
        )
    with pytest.raises(ValueError, match="episodes_per_position is frozen"):
        BreakoutRetestV2Strategy(
            [SYMBOL],
            BreakoutRetestV2Config(max_failure_watch_episodes_per_position=2),
        )


def test_buy_signal_without_fill_does_not_create_position_state() -> None:
    strategy = BreakoutRetestV2Strategy([SYMBOL])
    assert strategy.state[SYMBOL]["position_state"] is None


def test_actual_buy_fill_initializes_normal_position_from_fill_price_and_time() -> None:
    strategy = BreakoutRetestV2Strategy([SYMBOL])
    strategy.on_fill(_entry_signal(breakout_level=Decimal("99.5")), _fill(price=Decimal("101.25")))
    state = strategy.state[SYMBOL]
    assert state["position_state"] == "NORMAL_POSITION"
    assert state["position_entry_fill_time"] == T0.isoformat()
    assert state["position_entry_price"] == "101.25"
    assert state["position_breakout_level"] == "99.5"
    assert state["position_age_bars"] == 0
    assert state["failure_watch_used"] is False


def test_entry_fill_without_breakout_level_fails_closed() -> None:
    strategy = BreakoutRetestV2Strategy([SYMBOL])
    signal = _entry_signal()
    signal = Signal(
        action=signal.action,
        symbol=signal.symbol,
        price=signal.price,
        quantity=signal.quantity,
        timestamp=signal.timestamp,
        reason=signal.reason,
        strategy=signal.strategy,
        parameters_version=signal.parameters_version,
        metadata={},
    )
    with pytest.raises(ValueError, match="missing breakout_level"):
        strategy.on_fill(signal, _fill())


def test_position_bar_23_cannot_start_watch() -> None:
    strategy = _strategy()
    _advance_healthy(strategy, 21)
    assert strategy.should_exit(
        _candle(22, close=Decimal("98")),
        _indicators(ema20=Decimal("100"), ema50=Decimal("99")),
        _position(holding_periods=23),
    ) is None
    state = strategy.state[SYMBOL]
    assert state["position_age_bars"] == 23
    assert state["position_state"] == "NORMAL_POSITION"


def test_position_bar_24_can_start_watch_with_all_three_strict_failures() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    state = strategy.state[SYMBOL]
    assert state["position_age_bars"] == 24
    assert state["failure_watch_used"] is True
    assert state["failure_watch_start_time"] == (T0 + timedelta(hours=23)).isoformat()
    assert state["failure_watch_bars"] == 0
    assert state["failure_watch_trigger_close"] == "98"


@pytest.mark.parametrize(
    ("close", "ema20", "ema50", "breakout"),
    [
        (Decimal("100"), Decimal("100"), Decimal("101"), Decimal("101")),
        (Decimal("99"), Decimal("100"), Decimal("99"), Decimal("101")),
        (Decimal("100"), Decimal("101"), Decimal("102"), Decimal("100")),
    ],
)
def test_equality_with_any_failure_level_does_not_start_watch(
    close: Decimal,
    ema20: Decimal,
    ema50: Decimal,
    breakout: Decimal,
) -> None:
    strategy = BreakoutRetestV2Strategy([SYMBOL])
    strategy.on_fill(_entry_signal(breakout_level=breakout), _fill())
    _advance_healthy(strategy, 22)
    assert strategy.should_exit(
        _candle(23, close=close),
        _indicators(ema20=ema20, ema50=ema50),
        _position(holding_periods=24),
    ) is None
    assert strategy.state[SYMBOL]["position_state"] == "NORMAL_POSITION"


def test_missing_ema_does_not_start_watch() -> None:
    strategy = _strategy()
    _advance_healthy(strategy, 22)
    indicators = _indicators()
    indicators["ema_20"] = None
    assert strategy.should_exit(
        _candle(23, close=Decimal("98")), indicators, _position(holding_periods=24)
    ) is None
    assert strategy.state[SYMBOL]["position_state"] == "NORMAL_POSITION"


def test_trigger_candle_does_not_count_as_watch_bar_one() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    assert strategy.state[SYMBOL]["failure_watch_bars"] == 0
    assert strategy.should_exit(
        _candle(24, close=Decimal("98")),
        _indicators(),
        _position(holding_periods=25),
    ) is None
    assert strategy.state[SYMBOL]["failure_watch_bars"] == 1


def test_duplicate_candle_does_not_increment_position_or_watch_twice() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    candle = _candle(24, close=Decimal("98"))
    assert strategy.should_exit(candle, _indicators(), _position(holding_periods=25)) is None
    age = strategy.state[SYMBOL]["position_age_bars"]
    watch = strategy.state[SYMBOL]["failure_watch_bars"]
    assert strategy.should_exit(candle, _indicators(), _position(holding_periods=25)) is None
    assert strategy.state[SYMBOL]["position_age_bars"] == age
    assert strategy.state[SYMBOL]["failure_watch_bars"] == watch


def test_full_reclaim_recovers_to_normal_and_keeps_watch_used() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    assert strategy.should_exit(
        _candle(24, close=Decimal("101")),
        _indicators(ema20=Decimal("100"), ema50=Decimal("99")),
        _position(holding_periods=25),
    ) is None
    state = strategy.state[SYMBOL]
    assert state["position_state"] == "NORMAL_POSITION"
    assert state["failure_watch_used"] is True
    assert state["failure_watch_resolution"] == "RECOVERED"
    assert state["failure_watch_bars"] == 0


def test_partial_reclaim_does_not_recover() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    assert strategy.should_exit(
        _candle(24, close=Decimal("99.5")),
        _indicators(ema20=Decimal("99"), ema50=Decimal("98")),
        _position(holding_periods=25),
    ) is None
    assert strategy.state[SYMBOL]["position_state"] == "FAILURE_WATCH"


def test_recovery_equality_is_allowed() -> None:
    strategy = BreakoutRetestV2Strategy([SYMBOL])
    strategy.on_fill(_entry_signal(breakout_level=Decimal("100")), _fill())
    _advance_healthy(strategy, 22)
    assert strategy.should_exit(
        _candle(23, close=Decimal("98")),
        _indicators(ema20=Decimal("101"), ema50=Decimal("100")),
        _position(holding_periods=24),
    ) is None
    assert strategy.should_exit(
        _candle(24, close=Decimal("100")),
        _indicators(ema20=Decimal("100"), ema50=Decimal("100")),
        _position(holding_periods=25),
    ) is None
    assert strategy.state[SYMBOL]["position_state"] == "NORMAL_POSITION"


def test_recovered_position_cannot_start_second_watch() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    strategy.should_exit(
        _candle(24, close=Decimal("101")),
        _indicators(),
        _position(holding_periods=25),
    )
    for hour in range(25, 30):
        assert strategy.should_exit(
            _candle(hour, close=Decimal("98")),
            _indicators(),
            _position(holding_periods=hour + 1),
        ) is None
    state = strategy.state[SYMBOL]
    assert state["position_state"] == "NORMAL_POSITION"
    assert state["failure_watch_used"] is True


def test_watch_bar_23_does_not_timeout() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    for hour in range(24, 47):
        assert strategy.should_exit(
            _candle(hour, close=Decimal("98")),
            _indicators(),
            _position(holding_periods=hour + 1),
        ) is None
    assert strategy.state[SYMBOL]["failure_watch_bars"] == 23


def test_watch_bar_24_emits_one_causal_timeout_close_signal() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    for hour in range(24, 47):
        strategy.should_exit(
            _candle(hour, close=Decimal("98")),
            _indicators(),
            _position(holding_periods=hour + 1),
        )
    signal = strategy.should_exit(
        _candle(47, close=Decimal("98")),
        _indicators(),
        _position(holding_periods=48),
    )
    assert signal is not None
    assert str(signal.action) == "close"
    assert signal.reason == "Failure watch timeout without structural recovery"
    assert signal.timestamp == T0 + timedelta(hours=47)
    assert signal.metadata["failure_watch_bars"] == 24
    assert strategy.state[SYMBOL]["failure_watch_resolution"] == "TIMEOUT_SIGNAL"


def test_recovery_on_watch_bar_24_wins_before_timeout() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    for hour in range(24, 47):
        strategy.should_exit(
            _candle(hour, close=Decimal("98")),
            _indicators(),
            _position(holding_periods=hour + 1),
        )
    signal = strategy.should_exit(
        _candle(47, close=Decimal("101")),
        _indicators(),
        _position(holding_periods=48),
    )
    assert signal is None
    assert strategy.state[SYMBOL]["position_state"] == "NORMAL_POSITION"
    assert strategy.state[SYMBOL]["failure_watch_resolution"] == "RECOVERED"


def test_trend_down_has_precedence_during_watch() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    signal = strategy.should_exit(
        _candle(24, close=Decimal("98")),
        _indicators(regime=MarketRegime.TREND_DOWN),
        _position(holding_periods=25),
    )
    assert signal is not None
    assert signal.reason == "Regime changed to TREND_DOWN"
    assert strategy.state[SYMBOL]["failure_watch_bars"] == 0
    assert strategy.state[SYMBOL]["failure_watch_resolution"] == "TREND_DOWN"


def test_max_holding_has_precedence_during_watch() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    signal = strategy.should_exit(
        _candle(24, close=Decimal("101")),
        _indicators(),
        _position(holding_periods=100),
    )
    assert signal is not None
    assert signal.reason == "Max holding period reached"
    assert strategy.state[SYMBOL]["failure_watch_resolution"] == "MAX_HOLDING"


def test_dca_is_disabled_in_normal_and_watch_states() -> None:
    strategy = _strategy()
    assert strategy.should_add_dca(_candle(0), _indicators(), _position()) is None
    _start_watch(strategy)
    assert strategy.should_add_dca(_candle(24), _indicators(), _position()) is None


def test_close_fill_resets_position_management_only_after_fill() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    close_signal = Signal(
        action="close",
        symbol=SYMBOL,
        price=Decimal("98"),
        quantity=Decimal("1"),
        timestamp=T0 + timedelta(hours=24),
        reason="Regime changed to TREND_DOWN",
        strategy=strategy.name,
        parameters_version=strategy.config.parameters_version,
    )
    assert strategy.state[SYMBOL]["position_state"] == "FAILURE_WATCH"
    strategy.on_fill(
        close_signal,
        _fill(side="sell", price=Decimal("97.9"), when=T0 + timedelta(hours=25)),
    )
    state = strategy.state[SYMBOL]
    assert state["position_state"] is None
    assert state["failure_watch_used"] is False
    assert state["position_breakout_level"] is None


def test_stale_state_after_engine_owned_close_is_cleared_only_when_portfolio_has_no_position() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    assert strategy.state[SYMBOL]["position_state"] == "FAILURE_WATCH"
    strategy.should_enter(
        _candle(30),
        _indicators(),
        {"has_position": False, "capital": Decimal("500")},
    )
    assert strategy.state[SYMBOL]["position_state"] is None


def test_transition_events_are_serializable_dicts() -> None:
    strategy = _strategy()
    _start_watch(strategy)
    events = strategy.state[SYMBOL]["transition_events"]
    assert events[0]["event"] == "POSITION_NORMAL_STARTED"
    assert events[-1]["event"] == "FAILURE_WATCH_STARTED"
    assert all(isinstance(event["timestamp"], str) for event in events)


def test_two_strategy_instances_do_not_share_position_state() -> None:
    first = _strategy()
    second = _strategy()
    _start_watch(first)
    assert first.state[SYMBOL]["position_state"] == "FAILURE_WATCH"
    assert second.state[SYMBOL]["position_state"] == "NORMAL_POSITION"


def test_symbol_states_are_independent() -> None:
    strategy = BreakoutRetestV2Strategy(["BTCUSDT", "ETHUSDT"])
    strategy.on_fill(_entry_signal(), _fill())
    assert strategy.state["BTCUSDT"]["position_state"] == "NORMAL_POSITION"
    assert strategy.state["ETHUSDT"]["position_state"] is None
