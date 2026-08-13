from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.strategies.cts_trend_dca_v23 import (
    CTSBarSnapshot,
    CTSHTFSnapshot,
    CTSRegime,
    CTSTrendDCAV23Engine,
    PullbackState,
    classify_cts_regime,
    select_previous_confirmed_htf,
)

UTC = timezone.utc
BASE_TIME = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _bull_htf(open_hour: int = 0) -> CTSHTFSnapshot:
    open_time = BASE_TIME + timedelta(hours=open_hour)
    return CTSHTFSnapshot(
        open_time=open_time,
        close_time=open_time + timedelta(hours=4),
        close=Decimal("110"),
        ema_20=Decimal("108"),
        ema_50=Decimal("105"),
        ema_200=Decimal("100"),
        rsi_14=Decimal("55"),
    )


def _sideways_htf(open_hour: int = 0) -> CTSHTFSnapshot:
    open_time = BASE_TIME + timedelta(hours=open_hour)
    return CTSHTFSnapshot(
        open_time=open_time,
        close_time=open_time + timedelta(hours=4),
        close=Decimal("104"),
        ema_20=Decimal("105"),
        ema_50=Decimal("103"),
        ema_200=Decimal("100"),
        rsi_14=Decimal("49"),
    )


def _bar(
    index: int,
    *,
    htf: CTSHTFSnapshot | None = None,
    open_price: str = "106",
    low: str = "104.8",
    close: str = "105.2",
    previous_close: str = "105",
    ema_20: str = "105",
    ema_50: str = "103",
    ema_200: str = "100",
    rsi: str = "46",
    atr: str = "2",
    confirmed: bool = True,
) -> CTSBarSnapshot:
    return CTSBarSnapshot(
        symbol="BTCUSDT",
        open_time=BASE_TIME + timedelta(hours=index),
        open=Decimal(open_price),
        high=max(Decimal(open_price), Decimal(close)) + Decimal("1"),
        low=Decimal(low),
        close=Decimal(close),
        previous_close=Decimal(previous_close),
        ema_20=Decimal(ema_20),
        ema_50=Decimal(ema_50),
        ema_200=Decimal(ema_200),
        rsi_14=Decimal(rsi),
        atr_14=Decimal(atr),
        confirmed_htf=htf or _bull_htf(),
        bar_index=index,
        confirmed=confirmed,
    )


def test_cts_regime_contract_matches_pine_rules() -> None:
    assert (
        classify_cts_regime(
            close=Decimal("110"),
            ema_20=Decimal("108"),
            ema_50=Decimal("105"),
            ema_200=Decimal("100"),
            rsi_14=Decimal("55"),
        )
        == CTSRegime.BULL
    )
    assert (
        classify_cts_regime(
            close=Decimal("90"),
            ema_20=Decimal("92"),
            ema_50=Decimal("95"),
            ema_200=Decimal("100"),
            rsi_14=Decimal("45"),
        )
        == CTSRegime.BEAR
    )
    assert (
        classify_cts_regime(
            close=Decimal("104"),
            ema_20=Decimal("105"),
            ema_50=Decimal("103"),
            ema_200=Decimal("100"),
            rsi_14=Decimal("49"),
        )
        == CTSRegime.SIDEWAYS
    )


def test_sideways_htf_blocks_entry_and_resets_pullback() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1))
    assert engine.get_state("BTCUSDT").pullback_state == PullbackState.IN_PULLBACK

    decision = engine.evaluate(_bar(2, htf=_sideways_htf()))

    assert not decision.signal
    assert decision.reason_code == "HTF_NOT_BULL"
    assert decision.pullback_state == PullbackState.WAIT_PULLBACK
    assert "HTF" in decision.active_blocks


def test_valid_pullback_registers_state_but_does_not_emit_signal() -> None:
    engine = CTSTrendDCAV23Engine()

    decision = engine.evaluate(_bar(1, rsi="46", close="105.2", low="104.8"))

    assert not decision.signal
    assert decision.pullback_state == PullbackState.IN_PULLBACK
    assert decision.pullback_rsi == Decimal("46")
    assert engine.get_state("BTCUSDT").pullback_bar_index == 1


def test_rsi_recovery_below_point_five_waits() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))

    decision = engine.evaluate(
        _bar(
            2,
            open_price="104.9",
            close="105.3",
            low="104.9",
            rsi="46.4",
        )
    )

    assert not decision.signal
    assert decision.pullback_state == PullbackState.IN_PULLBACK
    assert decision.reason_code == "WAIT_RSI_RECOVERY"
    assert "RSI_RECOVERY" in decision.active_blocks


def test_rsi_recovery_equal_point_five_emits_candidate_and_locks() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))

    decision = engine.evaluate(
        _bar(
            2,
            open_price="104.9",
            close="105.3",
            low="104.9",
            rsi="46.5",
        )
    )

    assert decision.signal
    assert decision.decision_code == "CANDIDATE"
    assert decision.reason_code == "ENTRY_CONFIRMED"
    assert decision.pullback_state == PullbackState.LOCKED
    assert engine.get_state("BTCUSDT").last_dca_bar_index == 2


def test_rsi_can_recover_above_50_after_registered_pullback() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))

    decision = engine.evaluate(
        _bar(
            2,
            open_price="105.1",
            close="106",
            low="105",
            rsi="52",
        )
    )

    assert decision.signal
    assert decision.reason_code == "ENTRY_CONFIRMED"


def test_bearish_confirmation_candle_does_not_emit_signal() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))

    decision = engine.evaluate(
        _bar(
            2,
            open_price="106",
            close="105.3",
            low="104.9",
            rsi="47",
        )
    )

    assert not decision.signal
    assert decision.reason_code == "WAIT_BULLISH_CANDLE"


def test_close_below_ema20_does_not_confirm() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))

    decision = engine.evaluate(
        _bar(
            2,
            open_price="104",
            close="104.8",
            low="104.6",
            rsi="47",
        )
    )

    assert not decision.signal
    assert decision.reason_code == "WAIT_PRICE_RECOVERY"


def test_cooldown_blocks_new_pullback_for_first_23_bars() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))
    first_signal = engine.evaluate(
        _bar(2, open_price="104.9", close="105.3", rsi="47")
    )
    assert first_signal.signal

    for index in range(3, 26):
        decision = engine.evaluate(
            _bar(
                index,
                open_price="107",
                close="108",
                low="107",
                rsi="55",
            )
        )
        assert not decision.signal

    assert engine.get_state("BTCUSDT").pullback_state == PullbackState.LOCKED


def test_bar_24_plus_reset_rearms_then_next_pullback_can_start() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))
    engine.evaluate(_bar(2, open_price="104.9", close="105.3", rsi="47"))

    reset_bar = engine.evaluate(
        _bar(
            26,
            open_price="107",
            close="108",
            low="107",
            rsi="55",
        )
    )
    assert reset_bar.pullback_state == PullbackState.WAIT_PULLBACK
    assert reset_bar.cooldown_ready

    next_pullback = engine.evaluate(_bar(27, rsi="45", close="105.1", low="104.9"))
    assert next_pullback.pullback_state == PullbackState.IN_PULLBACK
    assert not next_pullback.signal


def test_bar_24_without_reset_remains_locked() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))
    engine.evaluate(_bar(2, open_price="104.9", close="105.3", rsi="47"))

    decision = engine.evaluate(
        _bar(
            26,
            open_price="105",
            close="105.2",
            low="104.9",
            rsi="47",
        )
    )

    assert decision.pullback_state == PullbackState.LOCKED
    assert not decision.signal


def test_htf_loss_resets_pullback_but_preserves_last_dca_index() -> None:
    engine = CTSTrendDCAV23Engine()
    engine.evaluate(_bar(1, rsi="46"))
    engine.evaluate(_bar(2, open_price="104.9", close="105.3", rsi="47"))
    assert engine.get_state("BTCUSDT").last_dca_bar_index == 2

    decision = engine.evaluate(_bar(3, htf=_sideways_htf()))

    state = engine.get_state("BTCUSDT")
    assert decision.pullback_state == PullbackState.WAIT_PULLBACK
    assert state.pullback_rsi is None
    assert state.last_dca_bar_index == 2


def test_live_bar_does_not_mutate_strategy_state() -> None:
    engine = CTSTrendDCAV23Engine()

    decision = engine.evaluate(_bar(1, rsi="46", confirmed=False))

    assert decision.reason_code == "WAIT_BAR_CLOSE"
    assert engine.get_state("BTCUSDT").pullback_state == PullbackState.WAIT_PULLBACK
    assert engine.get_state("BTCUSDT").pullback_rsi is None


def test_select_previous_confirmed_4h_matches_pine_previous_htf_semantics() -> None:
    htf_00 = _bull_htf(0)
    htf_04 = _bull_htf(4)
    htf_08 = _bull_htf(8)
    htf_12 = _bull_htf(12)
    history = [htf_00, htf_04, htf_08, htf_12]

    # During the 12:00-16:00 UTC bucket Pine expr[1] must keep using 08:00-12:00.
    for hour in (12, 13, 14, 15):
        selected = select_previous_confirmed_htf(BASE_TIME + timedelta(hours=hour), history)
        assert selected.open_time == BASE_TIME + timedelta(hours=8)
        assert selected.close_time == BASE_TIME + timedelta(hours=12)

    # At the next 4H bucket start, 12:00-16:00 becomes the previous confirmed bar.
    selected = select_previous_confirmed_htf(BASE_TIME + timedelta(hours=16), history)
    assert selected.open_time == BASE_TIME + timedelta(hours=12)
    assert selected.close_time == BASE_TIME + timedelta(hours=16)


def test_future_bars_do_not_change_prior_decisions() -> None:
    prefix = [
        _bar(1, rsi="46"),
        _bar(2, open_price="104.9", close="105.3", rsi="47"),
        _bar(3, open_price="107", close="108", low="107", rsi="55"),
    ]
    future = [
        _bar(4, htf=_sideways_htf(), close="90", ema_20="95", ema_50="100", ema_200="105"),
        _bar(5, htf=_sideways_htf(), close="80", ema_20="90", ema_50="100", ema_200="110"),
    ]

    prefix_engine = CTSTrendDCAV23Engine()
    baseline = [prefix_engine.evaluate(bar) for bar in prefix]

    extended_engine = CTSTrendDCAV23Engine()
    extended = [extended_engine.evaluate(bar) for bar in prefix + future]

    assert [decision.signal for decision in baseline] == [
        decision.signal for decision in extended[: len(prefix)]
    ]
    assert [decision.reason_code for decision in baseline] == [
        decision.reason_code for decision in extended[: len(prefix)]
    ]
    assert [decision.pullback_state for decision in baseline] == [
        decision.pullback_state for decision in extended[: len(prefix)]
    ]
