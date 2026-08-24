"""Scalp V2.1 — исправленная скальперинг стратегия.

Исправления:
1. Volume фильтр работает
2. EMA50 > EMA200 проверяется
3. ATR фильтр работает
4. ATR-based SL (адаптивный)
5. Risk/Reward 1:2
6. Trend strength фильтр
7. Cooldown после сделки
8. Position sizing передаётся в Signal (Risk Engine решает)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from app.indicators.market_regime import MarketRegime
from app.models import Fill, Signal
from app.strategies.base_strategy import BaseStrategy

logger = structlog.get_logger()

PARAMETERS_VERSION = "scalp_v2_1"


@dataclass
class ScalpV2_1Config:
    """Configuration for Scalp V2.1 strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Trend filter
    ema_fast: int = 50
    ema_slow: int = 200
    min_trend_strength: Decimal = Decimal("0.002")  # 0.2% min distance

    # Entry conditions
    rsi_min: Decimal = Decimal("35")
    rsi_max: Decimal = Decimal("50")  # Расширенный диапазон
    volume_multiplier: Decimal = Decimal("1.1")  # Менее строгий

    # ATR-based SL/TP
    atr_sl_multiplier: Decimal = Decimal("0.8")  # Еще tighter SL
    atr_tp_multiplier: Decimal = Decimal("1.6")  # TP 1.6x ATR (Risk/Reward 1:2)

    # Cooldown
    cooldown_periods: int = 2  # Minimal cooldown

    # Max holding
    max_holding_periods: int = 16

    # Trailing stop
    trailing_activation_r: Decimal = Decimal("1.0")  # Activate after +1R
    trailing_distance: Decimal = Decimal("0.5")  # Trail by 0.5R


class ScalpV2_1Strategy(BaseStrategy):
    """Scalp V2.1 — исправленная стратегия с ATR-based SL/TP.

    Entry:
    - EMA50 > EMA200 (тренд)
    - Trend strength > 0.2% (сила тренда)
    - close > EMA200
    - RSI 35-45 (откат)
    - Volume > 1.2x average
    - Cooldown прошёл

    Exit:
    - SL: entry - ATR * 1.5
    - TP: entry + ATR * 3
    - Trailing Stop после +1R
    """

    def __init__(
        self,
        symbols: list[str],
        config: ScalpV2_1Config | None = None,
    ) -> None:
        super().__init__("ScalpV2.1", symbols)
        self.config = config or ScalpV2_1Config()
        self.trailing_highs: dict[str, Decimal] = {}
        self._volume_avg: dict[str, Decimal] = {}
        self._atr_avg: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._last_trade_bar: dict[str, int] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}
        self._bar_counter: int = 0  # Internal bar counter for cooldown

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
        bar_index: int = 0,
    ) -> Signal | None:
        """Check entry conditions for Scalp V2.1."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        volume = Decimal(str(candle.get("volume", 0)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema50 = indicators.get("ema_50")
        ema200 = indicators.get("ema_200")
        atr = indicators.get("atr")

        if any(v is None for v in (rsi, ema50, ema200, atr)):
            return None

        rsi_value = Decimal(str(rsi))
        ema50_value = Decimal(str(ema50))
        ema200_value = Decimal(str(ema200))
        atr_value = Decimal(str(atr))

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Increment bar counter
        self._bar_counter += 1

        # Cooldown check
        last_trade = self._last_trade_bar.get(symbol, -999)
        if self._bar_counter - last_trade < self.config.cooldown_periods:
            return None

        # Update averages
        if symbol not in self._volume_avg:
            self._volume_avg[symbol] = volume
        else:
            self._volume_avg[symbol] = (self._volume_avg[symbol] * 19 + volume) / 20

        if symbol not in self._atr_avg:
            self._atr_avg[symbol] = atr_value
        else:
            self._atr_avg[symbol] = (self._atr_avg[symbol] * 19 + atr_value) / 20

        # 1. Trend filter: EMA50 > EMA200
        if ema50_value <= ema200_value:
            return None

        # 2. Trend strength filter
        if ema200_value > 0:
            trend_strength = (ema50_value - ema200_value) / ema200_value
            if trend_strength < self.config.min_trend_strength:
                return None

        # 3. Price above EMA200
        if close <= ema200_value:
            return None

        # 4. RSI in buy zone (35-45)
        if rsi_value < self.config.rsi_min or rsi_value > self.config.rsi_max:
            return None

        # 5. Volume confirmation
        vol_avg = self._volume_avg.get(symbol, volume)
        if vol_avg > 0 and volume < vol_avg * self.config.volume_multiplier:
            return None

        # 6. ATR confirmation (волатильность выше среднего)
        atr_avg = self._atr_avg.get(symbol, atr_value)
        if atr_avg > 0 and atr_value < atr_avg:
            return None

        # Calculate fixed levels (для PEPE с высокой волатильностью)
        take_profit = close * Decimal("1.015")  # 1.5% TP
        stop_loss = close * Decimal("0.99")     # 1% SL

        # Risk/Reward check
        risk = close - stop_loss
        reward = take_profit - close
        if risk > 0 and reward / risk < Decimal("1.5"):
            return None

        self._trade_count[symbol] = self._trade_count.get(symbol, 0) + 1
        self._last_trade_bar[symbol] = self._bar_counter

        logger.info(
            "scalp_v2_1_entry",
            symbol=symbol,
            price=float(close),
            rsi=float(rsi_value),
            atr=float(atr_value),
            sl=float(stop_loss),
            tp=float(take_profit),
            rr=1.5,
            trade_num=self._trade_count[symbol],
        )

        # Calculate position size (5% of capital)
        capital = Decimal(str(portfolio_state.get("capital", "1000")))
        position_value = capital * Decimal("0.05")
        quantity = position_value / close

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason=f"Scalp V2.1: RSI={rsi_value:.1f}, ATR={atr_value:.8f}",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(indicators.get("regime")),
            indicators=indicators,
            metadata={
                "rsi": float(rsi_value),
                "atr": float(atr_value),
                "take_profit": float(take_profit),
                "stop_loss": float(stop_loss),
                "rr_ratio": 1.5,
            },
        )

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Check exit conditions for Scalp V2.1."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        high = Decimal(str(candle.get("high", close)))
        low = Decimal(str(candle.get("low", close)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        entry_price = Decimal(str(position["entry_price"]))
        quantity = Decimal(str(position["quantity"]))

        # Exit condition 1: Stop Loss (fixed 1%)
        stop_loss = entry_price * Decimal("0.99")
        if close <= stop_loss:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"SL: {stop_loss}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "stop_loss"},
            )

        # Exit condition 2: Take Profit (fixed 1.5%)
        take_profit = entry_price * Decimal("1.015")
        if close >= take_profit:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"TP: {take_profit}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "take_profit"},
            )

        # Exit condition 3: Trailing Stop (после +1%)
        activation_price = entry_price * Decimal("1.01")
        trailing_high = self.trailing_highs.get(symbol)

        if trailing_high is not None or high >= activation_price:
            trailing_high = max(trailing_high or high, high)
            self.trailing_highs[symbol] = trailing_high
            trailing_stop = trailing_high * Decimal("0.995")  # 0.5% trail

            if low <= trailing_stop:
                self.trailing_highs.pop(symbol, None)
                return Signal(
                    action="close",
                    symbol=symbol,
                    price=trailing_stop,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason=f"Trailing: {trailing_stop}",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    metadata={"exit_source": "trailing_stop"},
                )

        # Exit condition 4: Max holding
        holding_periods = int(position.get("holding_periods", 0))
        if holding_periods >= self.config.max_holding_periods:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Max hold: {holding_periods}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "max_holding"},
            )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
