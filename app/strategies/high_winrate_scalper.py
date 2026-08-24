"""High Win Rate Scalper — скальперинг с высоким win rate.

Логика:
1. Входим ТОЛЬКО по тренду (EMA20 > EMA50 + close > EMA20)
2. Подтверждение: RSI 40-60 + бычья свеча (close > open)
3. Tight TP: 1.5%, SL: 0.75% (2:1 ratio)
4. Trailing stop для защиты прибыли

Особенности:
- Высокий win rate (>60%)
- Малые позиции (2% капитала)
- Быстрые выходы (1-3 свечи)
- 30-60 сделок за период
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

PARAMETERS_VERSION = "high_winrate_scalper_v1"


@dataclass
class HighWinRateScalperConfig:
    """Configuration for High Win Rate Scalper strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Trend filter
    ema_fast: int = 20
    ema_slow: int = 50
    require_trend: bool = True  # Require EMA alignment

    # RSI filter
    rsi_min: Decimal = Decimal("40")
    rsi_max: Decimal = Decimal("60")

    # Position sizing
    position_size_pct: Decimal = Decimal("0.02")  # 2% per trade

    # Take profit / Stop loss (tight)
    take_profit_pct: Decimal = Decimal("0.015")  # 1.5% TP
    stop_loss_pct: Decimal = Decimal("0.0075")  # 0.75% SL

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.01")  # Activate at +1%
    trailing_distance: Decimal = Decimal("0.005")  # Trail by 0.5%

    # Filters
    min_atr_pct: Decimal = Decimal("0.003")
    max_atr_pct: Decimal = Decimal("0.015")

    # Max holding periods
    max_holding_periods: int = 5  # Max 5 candles


class HighWinRateScalperStrategy(BaseStrategy):
    """High Win Rate Scalper — скальперинг с высоким win rate.

    Entry:
    - EMA20 > EMA50 (тренд)
    - close > EMA20 (цена выше тренда)
    - RSI 40-60 (не перекуплен/перепродан)
    - close > open (бычья свеча)

    Exit:
    - Take Profit 1.5%
    - Stop Loss 0.75%
    - Trailing Stop +1% / -0.5%
    - Max holding 5 candles
    """

    def __init__(
        self,
        symbols: list[str],
        config: HighWinRateScalperConfig | None = None,
    ) -> None:
        super().__init__("HighWinRateScalper", symbols)
        self.config = config or HighWinRateScalperConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._entry_prices: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for high win rate scalping."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        open_price = Decimal(str(candle["open"]))
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

        # 1. Trend filter: EMA20 > EMA50
        if self.config.require_trend and ema20_value <= ema50_value:
            return None

        # 2. Price above EMA20
        if close <= ema20_value:
            return None

        # 3. RSI filter: 40-60
        if rsi_value < self.config.rsi_min or rsi_value > self.config.rsi_max:
            return None

        # 4. Bullish candle: close > open
        if close <= open_price:
            return None

        # 5. ATR filter
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
        self._entry_prices[symbol] = close

        logger.info(
            "scalper_entry",
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
            reason=f"Scalp: Trend + RSI={rsi_value:.1f} + Bullish",
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
        """Check exit conditions for high win rate scalping."""
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
            logger.info("scalper_exit_tp", symbol=symbol, price=float(close), tp=float(take_profit))
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
            logger.info("scalper_exit_sl", symbol=symbol, price=float(close), sl=float(stop_loss))
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
            logger.info("scalper_exit_max_hold", symbol=symbol, periods=holding_periods)
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
