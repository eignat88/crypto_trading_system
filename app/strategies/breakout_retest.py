from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.indicators.market_regime import MarketRegime
from app.models import Fill, Signal
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy

PARAMETERS_VERSION = "breakout_retest_v1"
RESISTANCE_LOOKBACK_BARS = 20
RETEST_TIMEOUT_BARS = 24


@dataclass
class BreakoutRetestConfig(DCAConfig):
    """Frozen first-iteration configuration for Breakout Retest v1."""

    parameters_version: str = PARAMETERS_VERSION
    resistance_lookback_bars: int = RESISTANCE_LOOKBACK_BARS
    retest_timeout_bars: int = RETEST_TIMEOUT_BARS


class BreakoutRetestStrategy(TrendDCAStrategy):
    """Structural breakout -> retest-hold spot-long strategy.

    Entry logic is intentionally independent from TrendDCA's RSI pullback entry.
    Exit behavior and position sizing reuse the existing tested TrendDCA mechanics,
    while DCA additions are disabled by design for this strategy.

    Resistance is the maximum high of the exactly 20 completed candles preceding
    the current candle. The current high is appended only after the prior
    resistance has been calculated, preserving causality.
    """

    def __init__(
        self,
        symbols: list[str],
        config: BreakoutRetestConfig | None = None,
    ) -> None:
        frozen = config or BreakoutRetestConfig()
        if frozen.resistance_lookback_bars != RESISTANCE_LOOKBACK_BARS:
            raise ValueError(
                f"resistance_lookback_bars is frozen at {RESISTANCE_LOOKBACK_BARS} for v1"
            )
        if frozen.retest_timeout_bars != RETEST_TIMEOUT_BARS:
            raise ValueError(
                f"retest_timeout_bars is frozen at {RETEST_TIMEOUT_BARS} for v1"
            )
        super().__init__(symbols=symbols, config=frozen)
        self.name = "BreakoutRetest"
        self.config = frozen
        for symbol in symbols:
            self.state[symbol] = self._new_symbol_state()

    @staticmethod
    def _new_symbol_state() -> dict[str, Any]:
        return {
            "phase": "IDLE",
            "breakout": None,
            "recent_highs": [],
            "last_observed_time": None,
            "last_prior_resistance": None,
        }

    def _symbol_state(self, symbol: str) -> dict[str, Any]:
        return self.state.setdefault(symbol, self._new_symbol_state())

    @staticmethod
    def _as_decimal(value: Any) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @staticmethod
    def _serialize_time(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _clear_breakout(symbol_state: dict[str, Any]) -> None:
        symbol_state["phase"] = "IDLE"
        symbol_state["breakout"] = None

    def _observe_candle(self, candle: dict[str, Any]) -> Decimal | None:
        """Observe exactly one completed candle and return prior-20 resistance.

        Duplicate calls for the same timestamp are idempotent. This matters
        because an open-position candle can flow through should_exit and then
        should_add_dca; the current high must never be appended twice.
        """
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")
        high = self._as_decimal(candle.get("high", candle["close"]))
        symbol_state = self._symbol_state(symbol)

        if symbol_state.get("last_observed_time") == timestamp.isoformat():
            cached = symbol_state.get("last_prior_resistance")
            return None if cached is None else self._as_decimal(cached)

        highs = [self._as_decimal(value) for value in symbol_state.get("recent_highs", [])]
        resistance = (
            max(highs[-self.config.resistance_lookback_bars :])
            if len(highs) >= self.config.resistance_lookback_bars
            else None
        )

        highs.append(high)
        highs = highs[-self.config.resistance_lookback_bars :]
        symbol_state["recent_highs"] = [str(value) for value in highs]
        symbol_state["last_observed_time"] = timestamp.isoformat()
        symbol_state["last_prior_resistance"] = (
            None if resistance is None else str(resistance)
        )
        return resistance

    def _build_entry_signal(
        self,
        *,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
        breakout: dict[str, Any],
    ) -> Signal:
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        close = self._as_decimal(candle["close"])
        low = self._as_decimal(candle.get("low", close))
        capital = self._as_decimal(portfolio_state.get("capital", "0"))
        max_position_value = capital * self.config.max_capital_per_position
        base_order_value = max_position_value * self.config.base_order_pct
        quantity = base_order_value / close
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)
        regime = indicators.get("regime")

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason="Breakout retest held",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=None if regime is None else str(regime),
            indicators=indicators,
            metadata={
                "breakout_time": breakout["breakout_time"],
                "retest_time": self._serialize_time(timestamp),
                "breakout_level": breakout["breakout_level"],
                "breakout_close": breakout["breakout_close"],
                "retest_low": str(low),
                "retest_close": str(close),
                "bars_since_breakout": int(breakout["bars_since_breakout"]),
                "resistance_lookback_bars": self.config.resistance_lookback_bars,
                "retest_timeout_bars": self.config.retest_timeout_bars,
            },
        )

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Arm breakout or emit a later retest-hold entry signal."""
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        prior_resistance = self._observe_candle(candle)
        symbol_state = self._symbol_state(symbol)
        phase = str(symbol_state.get("phase") or "IDLE")
        breakout = symbol_state.get("breakout")

        close = self._as_decimal(candle["close"])
        low = self._as_decimal(candle.get("low", close))
        ema50_raw = indicators.get("ema_50")
        ema200_raw = indicators.get("ema_200")
        regime = indicators.get("regime")
        volatility_raw = indicators.get("volatility")
        has_position = bool(portfolio_state.get("has_position", False))

        # Missing required context never creates an entry. An armed setup still
        # ages causally so missing data cannot extend it indefinitely.
        if phase == "BREAKOUT_ARMED":
            if breakout is None:
                raise ValueError("BREAKOUT_ARMED state has no breakout payload")
            breakout["bars_since_breakout"] = int(breakout["bars_since_breakout"]) + 1

            if has_position:
                self._clear_breakout(symbol_state)
                return None
            if regime == MarketRegime.TREND_DOWN:
                self._clear_breakout(symbol_state)
                return None
            if int(breakout["bars_since_breakout"]) >= self.config.retest_timeout_bars:
                self._clear_breakout(symbol_state)
                return None
            if ema50_raw is None or ema200_raw is None or regime is None:
                return None

            ema50 = self._as_decimal(ema50_raw)
            ema200 = self._as_decimal(ema200_raw)
            if close <= ema200 or ema50 <= ema200:
                self._clear_breakout(symbol_state)
                return None

            volatility = (
                None if volatility_raw is None else self._as_decimal(volatility_raw)
            )
            if volatility is not None and volatility > Decimal("0.8"):
                return None

            breakout_level = self._as_decimal(breakout["breakout_level"])
            if low <= breakout_level and close >= breakout_level:
                signal = self._build_entry_signal(
                    candle=candle,
                    indicators=indicators,
                    portfolio_state=portfolio_state,
                    breakout=breakout,
                )
                self._clear_breakout(symbol_state)
                return signal
            return None

        # IDLE -> BREAKOUT_ARMED. No immediate BUY on the breakout candle.
        if has_position or prior_resistance is None:
            return None
        if ema50_raw is None or ema200_raw is None or regime is None:
            return None
        ema50 = self._as_decimal(ema50_raw)
        ema200 = self._as_decimal(ema200_raw)
        volatility = None if volatility_raw is None else self._as_decimal(volatility_raw)

        if close <= ema200:
            return None
        if ema50 <= ema200:
            return None
        if regime == MarketRegime.TREND_DOWN:
            return None
        if volatility is not None and volatility > Decimal("0.8"):
            return None
        if close <= prior_resistance:
            return None

        symbol_state["phase"] = "BREAKOUT_ARMED"
        symbol_state["breakout"] = {
            "breakout_time": self._serialize_time(timestamp),
            "breakout_level": str(prior_resistance),
            "breakout_close": str(close),
            "breakout_ema50": str(ema50),
            "breakout_ema200": str(ema200),
            "breakout_regime": str(regime),
            "bars_since_breakout": 0,
        }
        return None

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Reuse frozen baseline exit mechanics while continuing market history."""
        self._observe_candle(candle)
        return super().should_exit(candle, indicators, position)

    def should_add_dca(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """DCA is deliberately disabled for Breakout Retest v1."""
        self._observe_candle(candle)
        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """No DCA state; reset any stale trailing state on a new base fill."""
        if str(signal.action) in {"open_long", "SignalAction.OPEN_LONG"}:
            self.trailing_highs.pop(signal.symbol, None)
