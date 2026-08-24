"""Scalping Momentum Strategy — много сделок с коротким удержанием.

Логика:
1. Входим при RSI < 30 (перепроданность) + рост цены
2. Выходим при RSI > 70 (перекупленность) или TP/SL
3. Trailing stop для защиты прибыли

Особенности:
- Малые позиции (3% капитала)
- Быстрые входы/выходы
- Tight TP/SL (2-4%)
- Много сделок (30-50 за период)
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

PARAMETERS_VERSION = "scalping_momentum_v1"


@dataclass
class ScalpingMomentumConfig:
    """Configuration for Scalping Momentum strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Entry conditions
    rsi_oversold: Decimal = Decimal("35")  # Buy when RSI < 35
    rsi_overbought: Decimal = Decimal("65")  # Sell when RSI > 65

    # Position sizing
    position_size_pct: Decimal = Decimal("0.03")  # 3% per trade

    # Take profit / Stop loss
    take_profit_pct: Decimal = Decimal("0.03")  # 3% TP
    stop_loss_pct: Decimal = Decimal("0.015")  # 1.5% SL

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.02")  # Activate at +2%
    trailing_distance: Decimal = Decimal("0.01")  # Trail by 1%

    # Filters
    min_atr_pct: Decimal = Decimal("0.003")  # Min volatility
    max_atr_pct: Decimal = Decimal("0.015")  # Max volatility

    # Trend filter
    use_trend_filter: bool = True
    ema_fast: int = 20
    ema_slow: int = 50


class ScalpingMomentumStrategy(BaseStrategy):
    """Scalping Momentum — быстрые сделки на отскоках.

    Entry:
    - RSI < 35 (перепроданность)
    - close > previous close (рост)
    - ATR в пределах (волатильность适中)
    - (опционально) close > EMA20 (тренд)

    Exit:
    - RSI > 65 (перекупленность)
    - Take Profit 3%
    - Stop Loss 1.5%
    - Trailing Stop +2% / -1%
    """

    def __init__(
        self,
        symbols: list[str],
        config: ScalpingMomentumConfig | None = None,
    ) -> None:
        super().__init__("ScalpingMomentum", symbols)
        self.config = config or ScalpingMomentumConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for scalping."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema20 = indicators.get("ema_20")
        atr = indicators.get("atr")

        if any(v is None for v in (rsi,)):
            return None

        rsi_value = Decimal(str(rsi))
        ema20_value = Decimal(str(ema20)) if ema20 is not None else None
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Get previous close
        previous_close = self._previous_close.get(symbol, close)
        self._previous_close[symbol] = close

        # Entry conditions
        # 1. RSI oversold
        if rsi_value > self.config.rsi_oversold:
            return None

        # 2. Price rising
        if close <= previous_close:
            return None

        # 3. ATR filter (volatility)
        if atr_value is not None:
            atr_pct = atr_value / close
            if atr_pct < self.config.min_atr_pct or atr_pct > self.config.max_atr_pct:
                return None

        # 4. Trend filter (optional)
        if self.config.use_trend_filter and ema20_value is not None:
            if close < ema20_value:
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
            "scalping_entry",
            symbol=symbol,
            price=float(close),
            rsi=float(rsi_value),
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
            reason=f"Scalp: RSI={rsi_value:.1f}, TP={take_profit:.0f}, SL={stop_loss:.0f}",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(indicators.get("regime")),
            indicators=indicators,
            metadata={
                "rsi": float(rsi_value),
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
        """Check exit conditions for scalping."""
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

        # Exit condition 1: RSI overbought
        if rsi_value > self.config.rsi_overbought:
            logger.info("scalping_exit_rsi", symbol=symbol, rsi=float(rsi_value))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Exit: RSI={rsi_value:.1f} > {self.config.rsi_overbought}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "rsi_overbought"},
            )

        # Exit condition 2: Take Profit
        take_profit = entry_price * (Decimal("1") + self.config.take_profit_pct)
        if close >= take_profit:
            logger.info("scalping_exit_tp", symbol=symbol, price=float(close), tp=float(take_profit))
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
            logger.info("scalping_exit_sl", symbol=symbol, price=float(close), sl=float(stop_loss))
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
                logger.info("scalping_exit_trailing", symbol=symbol, price=float(close), trailing_stop=float(trailing_stop))
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
