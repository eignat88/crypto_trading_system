from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models import Fill, Signal
from app.strategies.breakout_retest import (
    BreakoutRetestConfig,
    BreakoutRetestStrategy,
    RESISTANCE_LOOKBACK_BARS,
    RETEST_TIMEOUT_BARS,
)

PARAMETERS_VERSION_V2 = "breakout_retest_v2"
FAILURE_DETECTION_AGE_BARS = 24
FAILURE_WATCH_MAX_BARS = 24


@dataclass
class BreakoutRetestV2Config(BreakoutRetestConfig):
    """Frozen Breakout Retest v2 configuration."""

    parameters_version: str = PARAMETERS_VERSION_V2
    failure_detection_age_bars: int = FAILURE_DETECTION_AGE_BARS
    failure_watch_max_bars: int = FAILURE_WATCH_MAX_BARS
    max_failure_watch_episodes_per_position: int = 1


class BreakoutRetestV2Strategy(BreakoutRetestStrategy):
    """Breakout Retest v2 with one causal FAILURE_WATCH episode per position."""

    def __init__(
        self,
        symbols: list[str],
        config: BreakoutRetestV2Config | None = None,
    ) -> None:
        frozen = config or BreakoutRetestV2Config()
        if frozen.resistance_lookback_bars != RESISTANCE_LOOKBACK_BARS:
            raise ValueError(
                f"resistance_lookback_bars is frozen at {RESISTANCE_LOOKBACK_BARS} for v2"
            )
        if frozen.retest_timeout_bars != RETEST_TIMEOUT_BARS:
            raise ValueError(
                f"retest_timeout_bars is frozen at {RETEST_TIMEOUT_BARS} for v2"
            )
        if frozen.failure_detection_age_bars != FAILURE_DETECTION_AGE_BARS:
            raise ValueError(
                f"failure_detection_age_bars is frozen at {FAILURE_DETECTION_AGE_BARS} for v2"
            )
        if frozen.failure_watch_max_bars != FAILURE_WATCH_MAX_BARS:
            raise ValueError(
                f"failure_watch_max_bars is frozen at {FAILURE_WATCH_MAX_BARS} for v2"
            )
        if frozen.max_failure_watch_episodes_per_position != 1:
            raise ValueError("max_failure_watch_episodes_per_position is frozen at 1 for v2")

        super().__init__(symbols=symbols, config=frozen)
        self.name = "BreakoutRetestV2"
        self.config = frozen

    @staticmethod
    def _new_symbol_state() -> dict[str, Any]:
        return {
            "phase": "IDLE",
            "breakout": None,
            "recent_highs": [],
            "last_observed_time": None,
            "last_prior_resistance": None,
            "position_state": None,
            "position_entry_fill_time": None,
            "position_entry_price": None,
            "position_breakout_level": None,
            "position_age_bars": 0,
            "last_position_observed_time": None,
            "failure_watch_used": False,
            "failure_watch_start_time": None,
            "failure_watch_bars": 0,
            "failure_watch_trigger_close": None,
            "failure_watch_trigger_ema20": None,
            "failure_watch_trigger_ema50": None,
            "failure_watch_trigger_breakout_level": None,
            "failure_watch_resolution": None,
            "failure_watch_resolution_time": None,
            "transition_events": [],
        }

    def _append_event(
        self,
        symbol_state: dict[str, Any],
        *,
        event: str,
        timestamp: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        events = list(symbol_state.get("transition_events") or [])
        events.append(
            {
                "event": event,
                "timestamp": timestamp.isoformat(),
                "strategy": self.name,
                "parameters_version": self.config.parameters_version,
                "metadata": metadata or {},
            }
        )
        symbol_state["transition_events"] = events

    @staticmethod
    def _clear_watch_fields(symbol_state: dict[str, Any]) -> None:
        symbol_state["failure_watch_start_time"] = None
        symbol_state["failure_watch_bars"] = 0
        symbol_state["failure_watch_trigger_close"] = None
        symbol_state["failure_watch_trigger_ema20"] = None
        symbol_state["failure_watch_trigger_ema50"] = None
        symbol_state["failure_watch_trigger_breakout_level"] = None

    def _reset_position_management(self, symbol_state: dict[str, Any]) -> None:
        symbol_state["position_state"] = None
        symbol_state["position_entry_fill_time"] = None
        symbol_state["position_entry_price"] = None
        symbol_state["position_breakout_level"] = None
        symbol_state["position_age_bars"] = 0
        symbol_state["last_position_observed_time"] = None
        symbol_state["failure_watch_used"] = False
        self._clear_watch_fields(symbol_state)
        symbol_state["failure_watch_resolution"] = None
        symbol_state["failure_watch_resolution_time"] = None

    def _observe_position_candle(
        self,
        symbol_state: dict[str, Any],
        timestamp: datetime,
    ) -> bool:
        """Increment position age once for a unique completed candle."""
        stamp = timestamp.isoformat()
        if symbol_state.get("last_position_observed_time") == stamp:
            return False
        symbol_state["last_position_observed_time"] = stamp
        symbol_state["position_age_bars"] = int(symbol_state.get("position_age_bars", 0)) + 1
        return True

    def _mark_watch_hard_exit(
        self,
        symbol_state: dict[str, Any],
        *,
        signal: Signal,
        timestamp: datetime,
    ) -> None:
        if symbol_state.get("position_state") != "FAILURE_WATCH":
            return
        reason_map = {
            "Regime changed to TREND_DOWN": "TREND_DOWN",
            "Max holding period reached": "MAX_HOLDING",
            "Trailing stop hit": "TRAILING",
            "Take profit hit": "TAKE_PROFIT",
            "Stop loss hit": "STOP_LOSS",
        }
        resolution = reason_map.get(signal.reason, f"HARD_EXIT:{signal.reason}")
        symbol_state["failure_watch_resolution"] = resolution
        symbol_state["failure_watch_resolution_time"] = timestamp.isoformat()
        self._append_event(
            symbol_state,
            event=f"FAILURE_WATCH_RESOLVED_BY_{resolution}",
            timestamp=timestamp,
            metadata={"reason": signal.reason},
        )

    def _build_watch_timeout_signal(
        self,
        *,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
        symbol_state: dict[str, Any],
    ) -> Signal:
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")
        close = self._as_decimal(candle["close"])
        quantity = self._as_decimal(position["quantity"])
        regime = indicators.get("regime")
        return Signal(
            action="close",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason="Failure watch timeout without structural recovery",
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            indicators=indicators,
            regime=None if regime is None else str(regime),
            metadata={
                "position_age_bars": int(symbol_state["position_age_bars"]),
                "failure_watch_bars": int(symbol_state["failure_watch_bars"]),
                "failure_watch_start_time": symbol_state["failure_watch_start_time"],
                "breakout_level": symbol_state["position_breakout_level"],
                "exit_source": "failure_watch_timeout",
            },
        )

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        symbol = str(candle["symbol"])
        symbol_state = self._symbol_state(symbol)

        if (
            not bool(portfolio_state.get("has_position", False))
            and symbol_state.get("position_state") is not None
        ):
            self._reset_position_management(symbol_state)

        return super().should_enter(candle, indicators, portfolio_state)

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")
        symbol_state = self._symbol_state(symbol)

        hard_exit = super().should_exit(candle, indicators, position)
        if hard_exit is not None:
            self._mark_watch_hard_exit(symbol_state, signal=hard_exit, timestamp=timestamp)
            return hard_exit

        if symbol_state.get("position_state") is None:
            raise ValueError(
                f"Open portfolio position for {symbol} has no v2 position-management state"
            )

        is_new_position_bar = self._observe_position_candle(symbol_state, timestamp)
        if not is_new_position_bar:
            return None

        close = self._as_decimal(candle["close"])
        ema20_raw = indicators.get("ema_20")
        ema50_raw = indicators.get("ema_50")
        breakout_level_raw = symbol_state.get("position_breakout_level")
        position_state = str(symbol_state.get("position_state"))

        if position_state == "NORMAL_POSITION":
            if bool(symbol_state.get("failure_watch_used", False)):
                return None
            if int(symbol_state["position_age_bars"]) < self.config.failure_detection_age_bars:
                return None
            if ema20_raw is None or ema50_raw is None:
                return None
            if breakout_level_raw is None:
                raise ValueError("Open v2 position is missing position_breakout_level")

            ema20 = self._as_decimal(ema20_raw)
            ema50 = self._as_decimal(ema50_raw)
            breakout_level = self._as_decimal(breakout_level_raw)
            if breakout_level <= 0:
                raise ValueError("position_breakout_level must be positive")

            if close < ema20 and close < ema50 and close < breakout_level:
                symbol_state["position_state"] = "FAILURE_WATCH"
                symbol_state["failure_watch_used"] = True
                symbol_state["failure_watch_start_time"] = timestamp.isoformat()
                symbol_state["failure_watch_bars"] = 0
                symbol_state["failure_watch_trigger_close"] = str(close)
                symbol_state["failure_watch_trigger_ema20"] = str(ema20)
                symbol_state["failure_watch_trigger_ema50"] = str(ema50)
                symbol_state["failure_watch_trigger_breakout_level"] = str(breakout_level)
                symbol_state["failure_watch_resolution"] = None
                symbol_state["failure_watch_resolution_time"] = None
                self._append_event(
                    symbol_state,
                    event="FAILURE_WATCH_STARTED",
                    timestamp=timestamp,
                    metadata={
                        "position_age_bars": int(symbol_state["position_age_bars"]),
                        "close": str(close),
                        "ema20": str(ema20),
                        "ema50": str(ema50),
                        "breakout_level": str(breakout_level),
                        "regime": None
                        if indicators.get("regime") is None
                        else str(indicators.get("regime")),
                    },
                )
            return None

        if position_state != "FAILURE_WATCH":
            raise ValueError(f"Unknown v2 position_state: {position_state}")

        symbol_state["failure_watch_bars"] = int(symbol_state.get("failure_watch_bars", 0)) + 1

        recovered = False
        if ema20_raw is not None and ema50_raw is not None:
            if breakout_level_raw is None:
                raise ValueError("FAILURE_WATCH is missing position_breakout_level")
            ema20 = self._as_decimal(ema20_raw)
            ema50 = self._as_decimal(ema50_raw)
            breakout_level = self._as_decimal(breakout_level_raw)
            recovered = close >= ema20 and close >= ema50 and close >= breakout_level

        if recovered:
            symbol_state["position_state"] = "NORMAL_POSITION"
            symbol_state["failure_watch_resolution"] = "RECOVERED"
            symbol_state["failure_watch_resolution_time"] = timestamp.isoformat()
            completed_watch_bars = int(symbol_state["failure_watch_bars"])
            self._append_event(
                symbol_state,
                event="FAILURE_WATCH_RECOVERED",
                timestamp=timestamp,
                metadata={"failure_watch_bars": completed_watch_bars},
            )
            return None

        if int(symbol_state["failure_watch_bars"]) >= self.config.failure_watch_max_bars:
            signal = self._build_watch_timeout_signal(
                candle=candle,
                indicators=indicators,
                position=position,
                symbol_state=symbol_state,
            )
            if symbol_state.get("failure_watch_resolution") != "TIMEOUT_SIGNAL":
                symbol_state["failure_watch_resolution"] = "TIMEOUT_SIGNAL"
                symbol_state["failure_watch_resolution_time"] = timestamp.isoformat()
                self._append_event(
                    symbol_state,
                    event="FAILURE_WATCH_TIMEOUT_SIGNAL",
                    timestamp=timestamp,
                    metadata={"failure_watch_bars": int(symbol_state["failure_watch_bars"])},
                )
            return signal

        return None

    def should_add_dca(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        self._observe_candle(candle)
        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        super().on_fill(signal, fill)
        symbol_state = self._symbol_state(signal.symbol)

        if fill.side == "buy":
            breakout_level = signal.metadata.get("breakout_level")
            if breakout_level is None:
                raise ValueError("Breakout Retest v2 entry fill is missing breakout_level metadata")
            level = self._as_decimal(breakout_level)
            if level <= 0:
                raise ValueError("breakout_level must be positive")

            self._reset_position_management(symbol_state)
            symbol_state["position_state"] = "NORMAL_POSITION"
            symbol_state["position_entry_fill_time"] = fill.timestamp.isoformat()
            symbol_state["position_entry_price"] = str(fill.price)
            symbol_state["position_breakout_level"] = str(level)
            symbol_state["position_age_bars"] = 0
            symbol_state["failure_watch_used"] = False
            self._append_event(
                symbol_state,
                event="POSITION_NORMAL_STARTED",
                timestamp=fill.timestamp,
                metadata={
                    "entry_price": str(fill.price),
                    "breakout_level": str(level),
                },
            )
            return

        if fill.side == "sell":
            self._append_event(
                symbol_state,
                event="POSITION_CLOSED",
                timestamp=fill.timestamp,
                metadata={"reason": signal.reason, "fill_price": str(fill.price)},
            )
            self._reset_position_management(symbol_state)
