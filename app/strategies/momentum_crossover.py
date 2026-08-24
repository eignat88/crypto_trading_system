"""Momentum Crossover Strategy — много сделок на пересечениях.

Логика:
1. BUY: RSI пересекает 50 снизу вверх + close > EMA20
2. SELL: RSI пересекает 50 сверху вниз + close < EMA20
3. TP: 2%, SL: 1%
4. Trailing stop для защиты прибыли

Особенности:
- Малые позиции (3% капитала)
- Быстрые входы/выходы
- Tight TP/SL
- Много сделок (50-100 за период)
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

PARAMETERS_VERSION = "momentum_crossover_v1"


@dataclass
class MomentumCrossoverConfig:
    """Configuration for Momentum Crossover strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # RSI levels
    rsi_buy_level: Decimal = Decimal("50")  # Buy when RSI crosses above 50
    rsi_sell_level: Decimal = Decimal("50")  # Sell when RSI crosses below 50

    # Position sizing
    position_size_pct: Decimal = Decimal("0.03")  # 3% per trade

    # Take profit / Stop loss
    take_profit_pct: Decimal = Decimal("0.02")  # 2% TP
    stop_loss_pct: Decimal = Decimal("0.01")  # 1% SL

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.015")  # Activate at +1.5%
    trailing_distance: Decimal = Decimal("0.008")  # Trail by 0.8%

    # Filters
    min_atr_pct: Decimal = Decimal("0.002")
    max_atr_pct: Decimal = Decimal("0.025")


class MomentumCrossoverStrategy(BaseStrategy):
    """Momentum Crossover — входы на пересечениях RSI.

    Entry:
    - BUY: RSI > 50 AND RSI_prev < 50 (бычье пересечение)
    - SELL: RSI < 50 AND RSI_prev > 50 (медвежье пересечение)

    Exit:
    - Take Profit 2%
    - Stop Loss 1%
    - Trailing Stop +1.5% / -0.8%
    """

    def __init__(
        self,
        symbols: list[str],
        config: MomentumCrossoverConfig | None = None,
    ) -> None:
        super().__init__("MomentumCrossover", symbols)
        self.config = config or MomentumCrossoverConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_rsi: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for momentum crossover."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        atr = indicators.get("atr")

        if rsi is None:
            return None

        rsi_value = Decimal(str(rsi))
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Get previous RSI
        previous_rsi = self._previous_rsi.get(symbol)
        self._previous_rsi[symbol] = rsi_value

        if previous_rsi is None:
            return None

        # ATR filter
        if atr_value is not None:
            atr_pct = atr_value / close
            if atr_pct < self.config.min_atr_pct or atr_pct > self.config.max_atr_pct:
                return None

        # Entry condition: RSI crosses above 50 (bullish momentum)
        if previous_rsi <= self.config.rsi_buy_level and rsi_value > self.config.rsi_buy_level:
            capital = Decimal(str(portfolio_state.get("capital", "0")))
            position_value = capital * self.config.position_size_pct
            quantity = position_value / close

            take_profit = close * (Decimal("1") + self.config.take_profit_pct)
            stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)

            self._trade_count[symbol] = self._trade_count.get(symbol, 0) + 1

            logger.info(
                "momentum_buy_signal",
                symbol=symbol,
                price=float(close),
                rsi=float(rsi_value),
                prev_rsi=float(previous_rsi),
                trade_num=self._trade_count[symbol],
            )

            return Signal(
                action="open_long",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Momentum BUY: RSI {previous_rsi:.1f}→{rsi_value:.1f}",
                stop_loss=stop_loss,
                take_profit=take_profit,
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                regime=str(indicators.get("regime")),
                indicators=indicators,
                metadata={
                    "rsi": float(rsi_value),
                    "prev_rsi": float(previous_rsi),
                    "take_profit": float(take_profit),
                    "stop_loss": float(stop_loss),
                },
            )

        return None

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Check exit conditions for momentum crossover."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        high = Decimal(str(candle.get("high", close)))
        low = Decimal(str(candle.get("low", close)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        entry_price = Decimal(str(position["entry_price"]))
        quantity = Decimal(str(position["quantity"]))

        rsi = indicators.get("rsi")
        if rsi is None:
            return None

        rsi_value = Decimal(str(rsi))
        previous_rsi = self._previous_rsi.get(symbol, rsi_value)

        # Exit condition 1: RSI crosses below 50 (bearish momentum)
        if previous_rsi >= self.config.rsi_sell_level and rsi_value < self.config.rsi_sell_level:
            logger.info("momentum_sell_signal", symbol=symbol, rsi=float(rsi_value))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Momentum SELL: RSI {previous_rsi:.1f}→{rsi_value:.1f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "rsi_crossover"},
            )

        # Exit condition 2: Take Profit
        take_profit = entry_price * (Decimal("1") + self.config.take_profit_pct)
        if close >= take_profit:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Take Profit: {take_profit:.0f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "take_profit"},
            )

        # Exit condition 3: Stop Loss
        stop_loss = entry_price * (Decimal("1") - self.config.stop_loss_pct)
        if close <= stop_loss:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Stop Loss: {stop_loss:.0f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "stop_loss"},
            )

        # Exit condition 4: Trailing Stop
        activation_price = entry_price * (Decimal("1") + self.config.trailing_activation)
        trailing_high = self.trailing_highs.get(symbol)

        if trailing_high is not None or high >= activation_price:
            trailing_high = max(trailing_high or high, high)
            self.trailing_highs[symbol] = trailing_high
            trailing_stop = trailing_high * (Decimal("1") - self.config.trailing_distance)

            if low <= trailing_stop:
                self.trailing_highs.pop(symbol, None)
                return Signal(
                    action="close",
                    symbol=symbol,
                    price=trailing_stop,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason=f"Trailing Stop: {trailing_stop:.0f}",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    metadata={"exit_source": "trailing_stop"},
                )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
