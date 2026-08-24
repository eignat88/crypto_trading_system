"""Momentum Breakout Strategy — входы на пробоях сильного моментума.

Логика:
1. Входим при сильном пробое (RSI > 60 + цена выше всех EMA)
2. Выходим по TP 8% или trailing stop
3. Сильный фильтр тренда

Особенности:
- Средние позиции (5% капитала)
- Удержание 1-10 дней
- TP 8%, trailing stop +5% / -3%
- 10-30 сделок за период
- Высокий win rate за счёт сильных входов
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

PARAMETERS_VERSION = "momentum_breakout_v1"


@dataclass
class MomentumBreakoutConfig:
    """Configuration for Momentum Breakout strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Entry conditions
    rsi_entry_min: Decimal = Decimal("55")  # Strong momentum
    ema_alignment_required: bool = True  # EMA20 > EMA50 > EMA200

    # Position sizing
    position_size_pct: Decimal = Decimal("0.05")  # 5% per trade

    # Take profit
    take_profit_pct: Decimal = Decimal("0.08")  # 8% TP

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.05")  # Activate at +5%
    trailing_distance: Decimal = Decimal("0.03")  # Trail by 3%

    # Stop loss (wide)
    stop_loss_pct: Decimal = Decimal("0.04")  # 4% SL

    # Filters
    min_atr_pct: Decimal = Decimal("0.005")
    max_atr_pct: Decimal = Decimal("0.020")

    # Max holding
    max_holding_periods: int = 20  # Max 20 candles (20 hours)


class MomentumBreakoutStrategy(BaseStrategy):
    """Momentum Breakout — входы на сильных пробоях.

    Entry:
    - RSI > 55 (сильный моментум)
    - close > EMA20 > EMA50 > EMA200 (выравнивание тренда)
    - close > previous_close (рост)

    Exit:
    - Take Profit 8%
    - Trailing Stop +5% / -3%
    - Stop Loss 4%
    - Max holding 20 candles
    """

    def __init__(
        self,
        symbols: list[str],
        config: MomentumBreakoutConfig | None = None,
    ) -> None:
        super().__init__("MomentumBreakout", symbols)
        self.config = config or MomentumBreakoutConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for momentum breakout."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema20 = indicators.get("ema_20")
        ema50 = indicators.get("ema_50")
        ema200 = indicators.get("ema_200")
        atr = indicators.get("atr")

        if any(v is None for v in (rsi, ema20, ema50)):
            return None

        rsi_value = Decimal(str(rsi))
        ema20_value = Decimal(str(ema20))
        ema50_value = Decimal(str(ema50))
        ema200_value = Decimal(str(ema200)) if ema200 is not None else None
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Get previous close
        previous_close = self._previous_close.get(symbol, close)
        self._previous_close[symbol] = close

        # 1. Strong momentum: RSI > 55
        if rsi_value < self.config.rsi_entry_min:
            return None

        # 2. EMA alignment: EMA20 > EMA50
        if ema20_value <= ema50_value:
            return None

        # 3. Optional: EMA200 alignment
        if self.config.ema_alignment_required and ema200_value is not None:
            if ema50_value <= ema200_value:
                return None

        # 4. Price above all EMAs
        if close <= ema20_value:
            return None

        # 5. Price rising
        if close <= previous_close:
            return None

        # 6. ATR filter
        if atr_value is not None:
            atr_pct = atr_value / close
            if atr_pct < self.config.min_atr_pct or atr_pct > self.config.max_atr_pct:
                return None

        # Calculate position size
        capital = Decimal(str(portfolio_state.get("capital", "0")))
        position_value = capital * self.config.position_size_pct
        quantity = position_value / close

        # Calculate levels
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)

        self._trade_count[symbol] = self._trade_count.get(symbol, 0) + 1

        logger.info(
            "breakout_entry",
            symbol=symbol,
            price=float(close),
            rsi=float(rsi_value),
            ema20=float(ema20_value),
            ema50=float(ema50_value),
            tp=float(take_profit),
            sl=float(stop_loss),
            trade_num=self._trade_count[symbol],
        )

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason=f"Breakout: RSI={rsi_value:.1f}, EMA aligned",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(indicators.get("regime")),
            indicators=indicators,
            metadata={
                "rsi": float(rsi_value),
                "ema20": float(ema20_value),
                "ema50": float(ema50_value),
                "take_profit": float(take_profit),
                "stop_loss": float(stop_loss),
            },
        )

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Check exit conditions for momentum breakout."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        high = Decimal(str(candle.get("high", close)))
        low = Decimal(str(candle.get("low", close)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        entry_price = Decimal(str(position["entry_price"]))
        quantity = Decimal(str(position["quantity"]))

        # Exit condition 1: Take Profit
        take_profit = entry_price * (Decimal("1") + self.config.take_profit_pct)
        if close >= take_profit:
            logger.info("breakout_exit_tp", symbol=symbol, price=float(close), tp=float(take_profit))
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

        # Exit condition 2: Stop Loss
        stop_loss = entry_price * (Decimal("1") - self.config.stop_loss_pct)
        if close <= stop_loss:
            logger.info("breakout_exit_sl", symbol=symbol, price=float(close), sl=float(stop_loss))
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

        # Exit condition 3: Trailing Stop
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

        # Exit condition 4: Max holding period
        holding_periods = int(position.get("holding_periods", 0))
        if holding_periods >= self.config.max_holding_periods:
            logger.info("breakout_exit_max_hold", symbol=symbol, periods=holding_periods)
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Max holding: {holding_periods}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "max_holding"},
            )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
