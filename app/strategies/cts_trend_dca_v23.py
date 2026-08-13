from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum


class CTSRegime(StrEnum):
    """TradingView CTS v2.3 market-regime labels."""

    BULL = "BULL"
    BEAR = "BEAR"
    SIDEWAYS = "SIDEWAYS"


class PullbackState(StrEnum):
    """State machine used by the TradingView CTS v2.3 reference script."""

    WAIT_PULLBACK = "WAIT_PULLBACK"
    IN_PULLBACK = "IN_PULLBACK"
    LOCKED = "LOCKED"


@dataclass(frozen=True)
class CTSTrendDCAV23Config:
    """Frozen baseline parameters copied from TradingView CTS MVP v2.3."""

    ema_fast: int = 20
    ema_medium: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rsi_regime_level: Decimal = Decimal("50")
    rsi_pullback_min: Decimal = Decimal("40")
    rsi_pullback_max: Decimal = Decimal("50")
    rsi_recovery_min: Decimal = Decimal("0.5")
    atr_period: int = 14
    pullback_atr_distance: Decimal = Decimal("0.35")
    pullback_exit_atr_distance: Decimal = Decimal("0.50")
    minimum_dca_interval_bars: int = 24
    require_rsi_recovery: bool = True
    require_bullish_candle: bool = True
    require_close_above_previous: bool = False
    parameters_version: str = "cts_trend_dca_v2_3"


@dataclass(frozen=True)
class CTSHTFSnapshot:
    """One fully closed higher-timeframe snapshot."""

    open_time: datetime
    close_time: datetime
    close: Decimal
    ema_20: Decimal
    ema_50: Decimal
    ema_200: Decimal
    rsi_14: Decimal

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise ValueError("HTF timestamps must be timezone-aware")
        if self.close_time <= self.open_time:
            raise ValueError("HTF close_time must be after open_time")


@dataclass(frozen=True)
class CTSBarSnapshot:
    """Precomputed 1H values consumed by the isolated CTS signal engine."""

    symbol: str
    open_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    previous_close: Decimal
    ema_20: Decimal
    ema_50: Decimal
    ema_200: Decimal
    rsi_14: Decimal
    atr_14: Decimal
    confirmed_htf: CTSHTFSnapshot
    bar_index: int
    confirmed: bool = True

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None:
            raise ValueError("1H open_time must be timezone-aware")
        if self.bar_index < 0:
            raise ValueError("bar_index must be non-negative")
        if self.atr_14 < 0:
            raise ValueError("ATR must be non-negative")


@dataclass
class CTSTrendDCAV23State:
    """Mutable per-symbol state required to reproduce the Pine state machine."""

    pullback_state: PullbackState = PullbackState.WAIT_PULLBACK
    pullback_rsi: Decimal | None = None
    pullback_price: Decimal | None = None
    pullback_bar_index: int | None = None
    last_dca_bar_index: int | None = None


@dataclass(frozen=True)
class CTSDecision:
    """One deterministic CTS v2.3 decision for a confirmed or live 1H bar."""

    symbol: str
    open_time: datetime
    signal: bool
    decision_code: str
    reason_code: str
    active_blocks: tuple[str, ...]
    htf_regime: CTSRegime
    local_regime: CTSRegime
    pullback_state: PullbackState
    pullback_rsi: Decimal | None
    last_dca_age: int | None
    cooldown_ready: bool
    confirmed_htf_open_time: datetime
    confirmed_htf_close_time: datetime


class CTSTrendDCAV23Engine:
    """Pure signal/state engine reproducing TradingView CTS MVP v2.3 logic.

    This class intentionally does not inherit from BaseStrategy and does not emit
    exchange orders. It is an isolated parity implementation that can be wired to
    the existing strategy/backtest interfaces only after TradingView parity is
    established.
    """

    def __init__(self, config: CTSTrendDCAV23Config | None = None) -> None:
        self.config = config or CTSTrendDCAV23Config()
        self._states: dict[str, CTSTrendDCAV23State] = {}

    def get_state(self, symbol: str) -> CTSTrendDCAV23State:
        """Return mutable state for diagnostics/tests."""
        return self._states.setdefault(symbol, CTSTrendDCAV23State())

    def evaluate(self, bar: CTSBarSnapshot) -> CTSDecision:
        """Evaluate one 1H bar in chronological order."""
        state = self.get_state(bar.symbol)
        config = self.config

        htf_regime = classify_cts_regime(
            close=bar.confirmed_htf.close,
            ema_20=bar.confirmed_htf.ema_20,
            ema_50=bar.confirmed_htf.ema_50,
            ema_200=bar.confirmed_htf.ema_200,
            rsi_14=bar.confirmed_htf.rsi_14,
            rsi_regime_level=config.rsi_regime_level,
        )
        local_regime = classify_cts_regime(
            close=bar.close,
            ema_20=bar.ema_20,
            ema_50=bar.ema_50,
            ema_200=bar.ema_200,
            rsi_14=bar.rsi_14,
            rsi_regime_level=config.rsi_regime_level,
        )

        htf_trend_filter = htf_regime == CTSRegime.BULL
        ema_structure_filter = bar.ema_20 > bar.ema_50
        ema_200_filter = bar.close > bar.ema_200
        trend_filter = htf_trend_filter and ema_structure_filter and ema_200_filter

        rsi_pullback_filter = (
            config.rsi_pullback_min <= bar.rsi_14 <= config.rsi_pullback_max
        )
        near_pullback_zone = _is_near_pullback_zone(bar, config)
        valid_pullback = trend_filter and rsi_pullback_filter and near_pullback_zone

        last_dca_age = (
            None
            if state.last_dca_bar_index is None
            else bar.bar_index - state.last_dca_bar_index
        )
        dca_interval_passed = (
            state.last_dca_bar_index is None
            or last_dca_age is not None
            and last_dca_age >= config.minimum_dca_interval_bars
        )

        rsi_recovery_filter = (
            not config.require_rsi_recovery
            or state.pullback_rsi is not None
            and bar.rsi_14 >= state.pullback_rsi + config.rsi_recovery_min
        )
        bullish_candle_filter = not config.require_bullish_candle or bar.close > bar.open
        previous_close_filter = (
            not config.require_close_above_previous or bar.close > bar.previous_close
        )
        price_recovery_filter = bar.close > bar.ema_20
        entry_confirmation = (
            bullish_candle_filter
            and previous_close_filter
            and price_recovery_filter
            and rsi_recovery_filter
        )

        new_signal = False

        if bar.confirmed:
            if not htf_trend_filter:
                _reset_pullback(state)
            elif state.pullback_state == PullbackState.WAIT_PULLBACK:
                if valid_pullback and dca_interval_passed:
                    state.pullback_state = PullbackState.IN_PULLBACK
                    state.pullback_rsi = bar.rsi_14
                    state.pullback_price = bar.close
                    state.pullback_bar_index = bar.bar_index
            elif state.pullback_state == PullbackState.IN_PULLBACK:
                if trend_filter and entry_confirmation and dca_interval_passed:
                    new_signal = True
                    state.last_dca_bar_index = bar.bar_index
                    state.pullback_state = PullbackState.LOCKED
                elif not trend_filter:
                    _reset_pullback(state)
                else:
                    pullback_finished_without_entry = (
                        bar.close
                        > bar.ema_20 + bar.atr_14 * config.pullback_exit_atr_distance
                    )
                    if pullback_finished_without_entry and not entry_confirmation:
                        _reset_pullback(state)
            elif state.pullback_state == PullbackState.LOCKED:
                pullback_reset = (
                    not near_pullback_zone
                    and bar.close
                    > bar.ema_20 + bar.atr_14 * config.pullback_exit_atr_distance
                )
                if pullback_reset and dca_interval_passed:
                    _reset_pullback(state)

        # Recalculate Pine-style display/decision values after state mutation.
        last_dca_age = (
            None
            if state.last_dca_bar_index is None
            else bar.bar_index - state.last_dca_bar_index
        )
        dca_interval_passed = (
            state.last_dca_bar_index is None
            or last_dca_age is not None
            and last_dca_age >= config.minimum_dca_interval_bars
        )
        rsi_recovery_filter = (
            not config.require_rsi_recovery
            or state.pullback_rsi is not None
            and bar.rsi_14 >= state.pullback_rsi + config.rsi_recovery_min
        )

        reason_code = _reason_code(
            confirmed=bar.confirmed,
            signal=new_signal,
            htf_trend_filter=htf_trend_filter,
            ema_structure_filter=ema_structure_filter,
            ema_200_filter=ema_200_filter,
            dca_interval_passed=dca_interval_passed,
            pullback_state=state.pullback_state,
            rsi_pullback_filter=rsi_pullback_filter,
            near_pullback_zone=near_pullback_zone,
            price_recovery_filter=price_recovery_filter,
            rsi_recovery_filter=rsi_recovery_filter,
            bullish_candle_filter=bullish_candle_filter,
            previous_close_filter=previous_close_filter,
        )
        active_blocks = _active_blocks(
            signal=new_signal,
            trend_filter=trend_filter,
            htf_trend_filter=htf_trend_filter,
            ema_structure_filter=ema_structure_filter,
            ema_200_filter=ema_200_filter,
            rsi_pullback_filter=rsi_pullback_filter,
            dca_interval_passed=dca_interval_passed,
            pullback_state=state.pullback_state,
            near_pullback_zone=near_pullback_zone,
            price_recovery_filter=price_recovery_filter,
            rsi_recovery_filter=rsi_recovery_filter,
            bullish_candle_filter=bullish_candle_filter,
            previous_close_filter=previous_close_filter,
        )

        return CTSDecision(
            symbol=bar.symbol,
            open_time=bar.open_time,
            signal=new_signal,
            decision_code="CANDIDATE" if new_signal else "NO_SIGNAL",
            reason_code=reason_code,
            active_blocks=active_blocks,
            htf_regime=htf_regime,
            local_regime=local_regime,
            pullback_state=state.pullback_state,
            pullback_rsi=state.pullback_rsi,
            last_dca_age=last_dca_age,
            cooldown_ready=dca_interval_passed,
            confirmed_htf_open_time=bar.confirmed_htf.open_time,
            confirmed_htf_close_time=bar.confirmed_htf.close_time,
        )


def classify_cts_regime(
    *,
    close: Decimal,
    ema_20: Decimal,
    ema_50: Decimal,
    ema_200: Decimal,
    rsi_14: Decimal,
    rsi_regime_level: Decimal = Decimal("50"),
) -> CTSRegime:
    """Classify regime exactly as the TradingView CTS v2.3 Pine script."""
    if (
        close > ema_20
        and ema_20 > ema_50
        and ema_50 > ema_200
        and rsi_14 > rsi_regime_level
    ):
        return CTSRegime.BULL
    if (
        close < ema_20
        and ema_20 < ema_50
        and ema_50 < ema_200
        and rsi_14 < rsi_regime_level
    ):
        return CTSRegime.BEAR
    return CTSRegime.SIDEWAYS


def select_previous_confirmed_htf(
    chart_open_time: datetime,
    htf_snapshots: list[CTSHTFSnapshot],
    *,
    timeframe_hours: int = 4,
) -> CTSHTFSnapshot:
    """Match Pine ``request.security(..., expr[1], lookahead_on)`` alignment.

    For a 1H bar inside the current 4H bucket, return the HTF bar that had fully
    closed at the start of that 4H bucket. This intentionally excludes the current
    forming HTF candle.
    """
    if chart_open_time.tzinfo is None:
        raise ValueError("chart_open_time must be timezone-aware")
    if timeframe_hours <= 0:
        raise ValueError("timeframe_hours must be positive")

    utc_time = chart_open_time.astimezone(timezone.utc)
    seconds = timeframe_hours * 60 * 60
    bucket_epoch = int(utc_time.timestamp()) // seconds * seconds
    bucket_start = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc)

    eligible = [
        snapshot
        for snapshot in htf_snapshots
        if snapshot.close_time.astimezone(timezone.utc) <= bucket_start
    ]
    if not eligible:
        raise ValueError("No previous confirmed HTF snapshot is available")
    return max(eligible, key=lambda item: item.close_time)


def _is_near_pullback_zone(
    bar: CTSBarSnapshot,
    config: CTSTrendDCAV23Config,
) -> bool:
    threshold = bar.atr_14 * config.pullback_atr_distance
    near_fast = (
        abs(bar.close - bar.ema_20) <= threshold
        or abs(bar.low - bar.ema_20) <= threshold
    )
    near_medium = (
        abs(bar.close - bar.ema_50) <= threshold
        or abs(bar.low - bar.ema_50) <= threshold
    )
    return near_fast or near_medium


def _reset_pullback(state: CTSTrendDCAV23State) -> None:
    state.pullback_state = PullbackState.WAIT_PULLBACK
    state.pullback_rsi = None
    state.pullback_price = None
    state.pullback_bar_index = None


def _reason_code(
    *,
    confirmed: bool,
    signal: bool,
    htf_trend_filter: bool,
    ema_structure_filter: bool,
    ema_200_filter: bool,
    dca_interval_passed: bool,
    pullback_state: PullbackState,
    rsi_pullback_filter: bool,
    near_pullback_zone: bool,
    price_recovery_filter: bool,
    rsi_recovery_filter: bool,
    bullish_candle_filter: bool,
    previous_close_filter: bool,
) -> str:
    if not confirmed:
        return "WAIT_BAR_CLOSE"
    if signal:
        return "ENTRY_CONFIRMED"
    if not htf_trend_filter:
        return "HTF_NOT_BULL"
    if not ema_structure_filter:
        return "EMA_STRUCTURE_NOT_BULL"
    if not ema_200_filter:
        return "PRICE_BELOW_EMA200"
    if not dca_interval_passed:
        return "DCA_COOLDOWN"
    if pullback_state == PullbackState.LOCKED:
        return "PULLBACK_ALREADY_USED"
    if pullback_state == PullbackState.WAIT_PULLBACK and not rsi_pullback_filter:
        return "RSI_OUTSIDE_PULLBACK_ZONE"
    if pullback_state == PullbackState.WAIT_PULLBACK and not near_pullback_zone:
        return "WAIT_PULLBACK"
    if pullback_state == PullbackState.IN_PULLBACK and not price_recovery_filter:
        return "WAIT_PRICE_RECOVERY"
    if pullback_state == PullbackState.IN_PULLBACK and not rsi_recovery_filter:
        return "WAIT_RSI_RECOVERY"
    if pullback_state == PullbackState.IN_PULLBACK and not bullish_candle_filter:
        return "WAIT_BULLISH_CANDLE"
    if pullback_state == PullbackState.IN_PULLBACK and not previous_close_filter:
        return "WAIT_PREVIOUS_CLOSE"
    return "NO_ENTRY"


def _active_blocks(
    *,
    signal: bool,
    trend_filter: bool,
    htf_trend_filter: bool,
    ema_structure_filter: bool,
    ema_200_filter: bool,
    rsi_pullback_filter: bool,
    dca_interval_passed: bool,
    pullback_state: PullbackState,
    near_pullback_zone: bool,
    price_recovery_filter: bool,
    rsi_recovery_filter: bool,
    bullish_candle_filter: bool,
    previous_close_filter: bool,
) -> tuple[str, ...]:
    blocks: list[str] = []
    if not htf_trend_filter:
        blocks.append("HTF")
    if not ema_structure_filter:
        blocks.append("EMA20/50")
    if not ema_200_filter:
        blocks.append("EMA200")
    if not rsi_pullback_filter and pullback_state == PullbackState.WAIT_PULLBACK:
        blocks.append("RSI")
    if not dca_interval_passed:
        blocks.append("COOLDOWN")
    if (
        trend_filter
        and dca_interval_passed
        and pullback_state == PullbackState.WAIT_PULLBACK
        and not near_pullback_zone
    ):
        blocks.append("PULLBACK")
    if trend_filter and pullback_state == PullbackState.IN_PULLBACK:
        if not price_recovery_filter:
            blocks.append("PRICE_RECOVERY")
        if not rsi_recovery_filter:
            blocks.append("RSI_RECOVERY")
        if not bullish_candle_filter:
            blocks.append("BULL_CANDLE")
        if not previous_close_filter:
            blocks.append("PREV_CLOSE")
    if pullback_state == PullbackState.LOCKED:
        blocks.append("LOCKED")
    if blocks:
        return tuple(blocks)
    return ("NONE",) if signal else ("WAIT",)
