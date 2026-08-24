"""Trend Following Strategy — следование за ценой.

Логика:
1. Входим когда цена пробивает EMA вверх (buy signal)
2. Держим позицию пока тренд продолжается
3. Выходим когда цена падает ниже EMA (sell signal)
4. Trailing stop следует за ценой

Особенности:
- Вход: close > EMA20 + close > EMA50 + volume spike
- Выход: close < EMA20 или trailing stop
- Trailing stop: +3% от максимума, -2% дистанция
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

PARAMETERS_VERSION = "trend_following_v1"


@dataclass
class TrendFollowingConfig:
    """Configuration for Trend Following strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Entry conditions
    ema_fast: int = 20  # Fast EMA
    ema_slow: int = 50  # Slow EMA
    volume_spike_pct: Decimal = Decimal("1.2")  # Volume must be 1.2x average

    # Exit conditions
    trailing_stop_activation: Decimal = Decimal("0.03")  # Activate at +3%
    trailing_stop_distance: Decimal = Decimal("0.02")  # Trail by 2%
    max_holding_periods: int = 100  # Max candles to hold

    # Risk limits
    max_position_size: Decimal = Decimal("0.10")  # 10% of capital
    max_risk_per_trade: Decimal = Decimal("0.02")  # 2% risk per trade

    # Stop loss
    stop_loss_pct: Decimal = Decimal("0.02")  # 2% stop loss


class TrendFollowingStrategy(BaseStrategy):
    """Trend Following — следование за ценой.

    Entry:
    - close > EMA20 (бычий моментум)
    - close > EMA50 (подтверждение тренда)
    - volume > average_volume * 1.2 (подтверждение объёмом)
    - close > previous_close (рост)

    Exit:
    - close < EMA20 (смена моментума)
    - trailing stop (защита прибыли)
    - max holding period
    """

    def __init__(
        self,
        symbols: list[str],
        config: TrendFollowingConfig | None = None,
    ) -> None:
        super().__init__("TrendFollowing", symbols)
        self.config = config or TrendFollowingConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._entry_prices: dict[str, Decimal] = {}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for trend following."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        volume = Decimal(str(candle.get("volume", 0)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        ema20 = indicators.get("ema_20")
        ema50 = indicators.get("ema_50")
        rsi = indicators.get("rsi")

        if any(v is None for v in (ema20, ema50)):
            return None

        ema20_value = Decimal(str(ema20))
        ema50_value = Decimal(str(ema50))

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Get previous close
        previous_close = self._previous_close.get(symbol, close)
        self._previous_close[symbol] = close

        # Entry conditions
        # 1. Price above EMA20 (momentum)
        if close <= ema20_value:
            return None

        # 2. Price above EMA50 (trend confirmation)
        if close <= ema50_value:
            return None

        # 3. EMA20 > EMA50 (bullish alignment)
        if ema20_value <= ema50_value:
            return None

        # 4. Price rising (momentum)
        if close <= previous_close:
            return None

        # 5. Volume confirmation (optional)
        # For now, skip volume check as we don't have average volume data

        # Calculate position size
        capital = Decimal(str(portfolio_state.get("capital", "0")))
        position_value = capital * self.config.max_position_size
        quantity = position_value / close

        # Calculate stop loss
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)

        logger.info(
            "trend_following_entry",
            symbol=symbol,
            price=float(close),
            ema20=float(ema20_value),
            ema50=float(ema50_value),
            stop_loss=float(stop_loss),
        )

        self._entry_prices[symbol] = close

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason=f"Trend Following: EMA20={ema20_value:.0f}, EMA50={ema50_value:.0f}",
            stop_loss=stop_loss,
            take_profit=close * Decimal("1.10"),  # 10% take profit
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(indicators.get("regime")),
            indicators=indicators,
            metadata={
                "ema20": float(ema20_value),
                "ema50": float(ema50_value),
                "entry_price": float(close),
            },
        )

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Check exit conditions for trend following."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        high = Decimal(str(candle.get("high", close)))
        low = Decimal(str(candle.get("low", close)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        entry_price = Decimal(str(position["entry_price"]))
        quantity = Decimal(str(position["quantity"]))

        ema20 = indicators.get("ema_20")
        if ema20 is None:
            return None

        ema20_value = Decimal(str(ema20))

        # Exit condition 1: Price below EMA20 (momentum reversal)
        if close < ema20_value:
            logger.info("trend_following_exit_ema", symbol=symbol, price=float(close), ema20=float(ema20_value))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Exit: price < EMA20 ({ema20_value:.0f})",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "ema_crossover"},
            )

        # Exit condition 2: Trailing stop
        activation_price = entry_price * (Decimal("1") + self.config.trailing_stop_activation)
        trailing_high = self.trailing_highs.get(symbol)

        if trailing_high is not None or high >= activation_price:
            trailing_high = max(trailing_high or high, high)
            self.trailing_highs[symbol] = trailing_high
            trailing_stop = trailing_high * (Decimal("1") - self.config.trailing_stop_distance)

            if low <= trailing_stop:
                self.trailing_highs.pop(symbol, None)
                logger.info("trend_following_exit_trailing", symbol=symbol, price=float(close), trailing_stop=float(trailing_stop))
                return Signal(
                    action="close",
                    symbol=symbol,
                    price=trailing_stop,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason=f"Trailing stop: {trailing_stop:.0f}",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    metadata={"exit_source": "trailing_stop"},
                )

        # Exit condition 3: Max holding period
        holding_periods = int(position.get("holding_periods", 0))
        if holding_periods >= self.config.max_holding_periods:
            logger.info("trend_following_exit_max_hold", symbol=symbol, periods=holding_periods)
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Max holding period: {holding_periods}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "max_holding"},
            )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
