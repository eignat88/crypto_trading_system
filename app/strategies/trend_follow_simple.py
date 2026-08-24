"""Trend Follow Simple — простая стратегия следования за трендом.

Логика:
1. BUY: EMA20 > EMA50 + close > EMA20 + RSI 40-60
2. SELL: EMA20 < EMA50 или close < EMA20
3. TP 5%, SL 3%
4. Trailing stop

Простая и понятная стратегия для MVP.
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

PARAMETERS_VERSION = "trend_follow_simple"


@dataclass
class TrendFollowSimpleConfig:
    """Configuration for Trend Follow Simple strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Entry conditions
    rsi_min: Decimal = Decimal("40")
    rsi_max: Decimal = Decimal("60")

    # Position sizing
    position_size_pct: Decimal = Decimal("0.10")  # 10%

    # Take profit / Stop loss
    take_profit_pct: Decimal = Decimal("0.05")  # 5%
    stop_loss_pct: Decimal = Decimal("0.03")  # 3%

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.03")  # +3%
    trailing_distance: Decimal = Decimal("0.02")  # -2%


class TrendFollowSimpleStrategy(BaseStrategy):
    """Trend Follow Simple — простая стратегия следования за трендом.

    Entry:
    - EMA20 > EMA50 (тренд)
    - close > EMA20 (цена выше тренда)
    - RSI 40-60 (не перекуплен/перепродан)

    Exit:
    - Take Profit 5%
    - Stop Loss 3%
    - Trailing Stop +3% / -2%
    """

    def __init__(
        self,
        symbols: list[str],
        config: TrendFollowSimpleConfig | None = None,
    ) -> None:
        super().__init__("TrendFollowSimple", symbols)
        self.config = config or TrendFollowSimpleConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema20 = indicators.get("ema_20")
        ema50 = indicators.get("ema_50")

        if any(v is None for v in (rsi, ema20, ema50)):
            return None

        rsi_value = Decimal(str(rsi))
        ema20_value = Decimal(str(ema20))
        ema50_value = Decimal(str(ema50))

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Entry conditions
        # 1. EMA20 > EMA50 (тренд)
        if ema20_value <= ema50_value:
            return None

        # 2. Price above EMA20
        if close <= ema20_value:
            return None

        # 3. RSI 40-60
        if rsi_value < self.config.rsi_min or rsi_value > self.config.rsi_max:
            return None

        # Calculate position size
        capital = Decimal(str(portfolio_state.get("capital", "1000")))
        position_value = capital * self.config.position_size_pct
        quantity = position_value / close

        # Calculate levels
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)

        self._trade_count[symbol] = self._trade_count.get(symbol, 0) + 1

        logger.info(
            "trend_follow_entry",
            symbol=symbol,
            price=float(close),
            rsi=float(rsi_value),
            ema20=float(ema20_value),
            ema50=float(ema50_value),
            trade_num=self._trade_count[symbol],
        )

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason=f"Trend Follow: EMA20>{ema50_value:.0f}, RSI={rsi_value:.1f}",
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
            },
        )

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Check exit conditions."""
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
        ema50 = indicators.get("ema_50")

        if ema20 is None or ema50 is None:
            return None

        ema20_value = Decimal(str(ema20))
        ema50_value = Decimal(str(ema50))

        # Exit condition 1: Take Profit
        take_profit = entry_price * (Decimal("1") + self.config.take_profit_pct)
        if close >= take_profit:
            return Signal(
                action="close", symbol=symbol, price=close, quantity=quantity,
                timestamp=timestamp, reason=f"TP: {take_profit:.2f}",
                strategy=self.name, parameters_version=self.config.parameters_version,
                indicators=indicators, metadata={"exit_source": "take_profit"},
            )

        # Exit condition 2: Stop Loss
        stop_loss = entry_price * (Decimal("1") - self.config.stop_loss_pct)
        if close <= stop_loss:
            return Signal(
                action="close", symbol=symbol, price=close, quantity=quantity,
                timestamp=timestamp, reason=f"SL: {stop_loss:.2f}",
                strategy=self.name, parameters_version=self.config.parameters_version,
                indicators=indicators, metadata={"exit_source": "stop_loss"},
            )

        # Exit condition 3: Trend reversal
        if ema20_value < ema50_value:
            return Signal(
                action="close", symbol=symbol, price=close, quantity=quantity,
                timestamp=timestamp, reason=f"Trend reversal: EMA20 < EMA50",
                strategy=self.name, parameters_version=self.config.parameters_version,
                indicators=indicators, metadata={"exit_source": "trend_reversal"},
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
                    action="close", symbol=symbol, price=trailing_stop, quantity=quantity,
                    timestamp=timestamp, reason=f"Trailing: {trailing_stop:.2f}",
                    strategy=self.name, parameters_version=self.config.parameters_version,
                    indicators=indicators, metadata={"exit_source": "trailing_stop"},
                )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        pass
