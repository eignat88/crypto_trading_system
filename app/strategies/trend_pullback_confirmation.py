from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.indicators.market_regime import MarketRegime
from app.models import Signal
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy


PARAMETERS_VERSION = "trend_pullback_confirmation_v1"
SETUP_TIMEOUT_BARS = 12


@dataclass
class TrendPullbackConfirmationConfig(DCAConfig):
    """Frozen first-iteration configuration for Trend Pullback Confirmation v1."""

    parameters_version: str = PARAMETERS_VERSION
    setup_timeout_bars: int = SETUP_TIMEOUT_BARS


class TrendPullbackConfirmationStrategy(TrendDCAStrategy):
    """TrendDCA exits/DCA with a two-stage pullback-confirmation base entry.

    Only the initial entry mechanism differs from TrendDCA v1. The strategy
    arms a pullback when RSI <= 45 inside TREND_UP, then waits for a strict RSI
    cross back above 45 while price is above EMA20. The resulting signal keeps
    the existing next-candle-open execution contract owned by BacktestEngine.
    """

    def __init__(
        self,
        symbols: list[str],
        config: TrendPullbackConfirmationConfig | None = None,
    ) -> None:
        frozen = config or TrendPullbackConfirmationConfig()
        if frozen.setup_timeout_bars != SETUP_TIMEOUT_BARS:
            raise ValueError(
                f"setup_timeout_bars is frozen at {SETUP_TIMEOUT_BARS} for v1"
            )
        super().__init__(symbols=symbols, config=frozen)
        self.config = frozen
        for symbol in symbols:
            self.state[symbol] = {
                "phase": "IDLE",
                "previous_rsi": None,
                "setup": None,
            }

    def _symbol_state(self, symbol: str) -> dict[str, Any]:
        return self.state.setdefault(
            symbol,
            {"phase": "IDLE", "previous_rsi": None, "setup": None},
        )

    @staticmethod
    def _serialize_decimal(value: Decimal) -> str:
        return str(value)

    @staticmethod
    def _serialize_time(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _clear_setup(symbol_state: dict[str, Any]) -> None:
        symbol_state["phase"] = "IDLE"
        symbol_state["setup"] = None

    def _arm_setup(
        self,
        *,
        symbol_state: dict[str, Any],
        timestamp: datetime,
        close: Decimal,
        ema20: Decimal,
        ema50: Decimal,
        ema200: Decimal,
        rsi: Decimal,
        regime: Any,
    ) -> None:
        symbol_state["phase"] = "PULLBACK_ARMED"
        symbol_state["setup"] = {
            "setup_time": self._serialize_time(timestamp),
            "setup_rsi": self._serialize_decimal(rsi),
            "setup_close": self._serialize_decimal(close),
            "setup_ema20": self._serialize_decimal(ema20),
            "setup_ema50": self._serialize_decimal(ema50),
            "setup_ema200": self._serialize_decimal(ema200),
            "setup_regime": str(regime),
            "bars_since_setup": 0,
        }

    def _build_confirmed_signal(
        self,
        *,
        symbol: str,
        timestamp: datetime,
        close: Decimal,
        ema20: Decimal,
        ema50: Decimal,
        ema200: Decimal,
        rsi: Decimal,
        regime: Any,
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
        setup: dict[str, Any],
    ) -> Signal:
        capital = Decimal(str(portfolio_state.get("capital", "0")))
        max_position_value = capital * self.config.max_capital_per_position
        base_order_value = max_position_value * self.config.base_order_pct
        quantity = base_order_value / close
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason="Trend pullback recovery confirmed",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(regime),
            indicators=indicators,
            metadata={
                "dca_level": 0,
                "setup_time": setup["setup_time"],
                "confirmation_time": self._serialize_time(timestamp),
                "setup_rsi": setup["setup_rsi"],
                "confirmation_rsi": str(rsi),
                "bars_since_setup": int(setup["bars_since_setup"]),
                "confirmation_close": str(close),
                "confirmation_ema20": str(ema20),
                "confirmation_ema50": str(ema50),
                "confirmation_ema200": str(ema200),
            },
        )

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        symbol_state = self._symbol_state(symbol)
        previous_rsi_raw = symbol_state.get("previous_rsi")
        previous_rsi = (
            Decimal(str(previous_rsi_raw)) if previous_rsi_raw is not None else None
        )

        close = Decimal(str(candle["close"]))
        ema20_raw = indicators.get("ema_20")
        ema50_raw = indicators.get("ema_50")
        ema200_raw = indicators.get("ema_200")
        rsi_raw = indicators.get("rsi")
        regime = indicators.get("regime")
        volatility_raw = indicators.get("volatility")

        # Previous RSI is part of serializable strategy state. Updating it uses
        # only the just-closed current candle and cannot create a signal itself.
        if rsi_raw is not None:
            symbol_state["previous_rsi"] = str(Decimal(str(rsi_raw)))

        if any(
            value is None
            for value in (ema20_raw, ema50_raw, ema200_raw, rsi_raw, regime)
        ):
            return None

        ema20 = Decimal(str(ema20_raw))
        ema50 = Decimal(str(ema50_raw))
        ema200 = Decimal(str(ema200_raw))
        rsi = Decimal(str(rsi_raw))
        volatility = (
            Decimal(str(volatility_raw)) if volatility_raw is not None else None
        )
        has_position = bool(portfolio_state.get("has_position", False))

        phase = str(symbol_state.get("phase") or "IDLE")
        setup = symbol_state.get("setup")

        if phase == "PULLBACK_ARMED":
            if setup is None:
                raise ValueError("PULLBACK_ARMED state has no setup payload")

            setup["bars_since_setup"] = int(setup["bars_since_setup"]) + 1

            # Frozen cancellation rules are evaluated before confirmation.
            if (
                regime != MarketRegime.TREND_UP
                or close <= ema200
                or ema50 <= ema200
                or has_position
                or int(setup["bars_since_setup"]) >= self.config.setup_timeout_bars
            ):
                self._clear_setup(symbol_state)
                return None

            crossed_up = (
                previous_rsi is not None
                and previous_rsi <= Decimal("45")
                and rsi > Decimal("45")
            )
            confirmed = (
                crossed_up
                and close > ema20
                and (volatility is None or volatility <= Decimal("0.8"))
            )
            if not confirmed:
                return None

            signal = self._build_confirmed_signal(
                symbol=symbol,
                timestamp=timestamp,
                close=close,
                ema20=ema20,
                ema50=ema50,
                ema200=ema200,
                rsi=rsi,
                regime=regime,
                indicators=indicators,
                portfolio_state=portfolio_state,
                setup=setup,
            )
            self._clear_setup(symbol_state)
            return signal

        # IDLE -> PULLBACK_ARMED. No signal is emitted on the setup candle.
        if has_position:
            return None
        if regime != MarketRegime.TREND_UP:
            return None
        if close <= ema200 or ema50 <= ema200:
            return None
        if rsi > Decimal("45"):
            return None
        if volatility is not None and volatility > Decimal("0.8"):
            return None

        self._arm_setup(
            symbol_state=symbol_state,
            timestamp=timestamp,
            close=close,
            ema20=ema20,
            ema50=ema50,
            ema200=ema200,
            rsi=rsi,
            regime=regime,
        )
        return None
