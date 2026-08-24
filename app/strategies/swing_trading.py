"""Swing Trading Strategy — среднесрочные сделки 1-5 дней.

Логика:
1. Входим при сильном моментуме (RSI 40-60 + EMA crossover)
2. Выходим по TP 5% или SL 3%
3. Trailing stop для защиты прибыли
4. Фильтр тренда для снижения ложных сигналов

Особенности:
- Средние позиции (5% капитала)
- Удержание 1-5 дней
- TP 5%, SL 3%
- 10-30 сделок за период
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

PARAMETERS_VERSION = "swing_trading_v1"


@dataclass
class SwingTradingConfig:
    """Configuration for Swing Trading strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Entry conditions
    rsi_buy_min: Decimal = Decimal("40")  # Min RSI for buy
    rsi_buy_max: Decimal = Decimal("60")  # Max RSI for buy
    rsi_sell_min: Decimal = Decimal("40")  # Min RSI for sell
    rsi_sell_max: Decimal = Decimal("60")  # Max RSI for sell

    # Position sizing
    position_size_pct: Decimal = Decimal("0.05")  # 5% per trade

    # Take profit / Stop loss
    take_profit_pct: Decimal = Decimal("0.05")  # 5% TP
    stop_loss_pct: Decimal = Decimal("0.03")  # 3% SL

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.04")  # Activate at +4%
    trailing_distance: Decimal = Decimal("0.02")  # Trail by 2%

    # Trend filter
    ema_fast: int = 20
    ema_slow: int = 50
    require_trend: bool = True  # Require EMA alignment

    # Volatility filter
    min_atr_pct: Decimal = Decimal("0.005")
    max_atr_pct: Decimal = Decimal("0.020")


class SwingTradingStrategy(BaseStrategy):
    """Swing Trading — среднесрочные сделки на трендах.

    Entry:
    - BUY: EMA20 > EMA50 + RSI 40-60 + close > EMA20
    - SELL: EMA20 < EMA50 + RSI 40-60 + close < EMA20

    Exit:
    - Take Profit 5%
    - Stop Loss 3%
    - Trailing Stop +4% / -2%
    """

    def __init__(
        self,
        symbols: list[str],
        config: SwingTradingConfig | None = None,
    ) -> None:
        super().__init__("SwingTrading", symbols)
        self.config = config or SwingTradingConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._entry_prices: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for swing trading."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema20 = indicators.get("ema_20")
        ema50 = indicators.get("ema_50")
        atr = indicators.get("atr")

        if any(v is None for v in (rsi, ema20, ema50)):
            return None

        rsi_value = Decimal(str(rsi))
        ema20_value = Decimal(str(ema20))
        ema50_value = Decimal(str(ema50))
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # ATR filter
        if atr_value is not None:
            atr_pct = atr_value / close
            if atr_pct < self.config.min_atr_pct or atr_pct > self.config.max_atr_pct:
                return None

        # Trend filter
        if self.config.require_trend:
            if ema20_value <= ema50_value:
                return None

        # RSI filter
        if rsi_value < self.config.rsi_buy_min or rsi_value > self.config.rsi_buy_max:
            return None

        # Price above EMA20
        if close <= ema20_value:
            return None

        # Calculate position size
        capital = Decimal(str(portfolio_state.get("capital", "0")))
        position_value = capital * self.config.position_size_pct
        quantity = position_value / close

        # Calculate levels
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)

        self._trade_count[symbol] = self._trade_count.get(symbol, 0) + 1
        self._entry_prices[symbol] = close

        logger.info(
            "swing_entry",
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
            reason=f"Swing BUY: RSI={rsi_value:.1f}, EMA20>{ema50_value:.0f}",
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
        """Check exit conditions for swing trading."""
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
        ema20 = indicators.get("ema_20")
        ema50 = indicators.get("ema_50")

        if rsi is None or ema20 is None or ema50 is None:
            return None

        rsi_value = Decimal(str(rsi))
        ema20_value = Decimal(str(ema20))
        ema50_value = Decimal(str(ema50))

        # Exit condition 1: Trend reversal
        if ema20_value < ema50_value:
            logger.info("swing_exit_trend", symbol=symbol)
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Exit: EMA20 < EMA50 ({ema20_value:.0f} < {ema50_value:.0f})",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "trend_reversal"},
            )

        # Exit condition 2: RSI overbought
        if rsi_value > Decimal("70"):
            logger.info("swing_exit_rsi", symbol=symbol, rsi=float(rsi_value))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Exit: RSI={rsi_value:.1f} > 70",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "rsi_overbought"},
            )

        # Exit condition 3: Take Profit
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

        # Exit condition 4: Stop Loss
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

        # Exit condition 5: Trailing Stop
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
