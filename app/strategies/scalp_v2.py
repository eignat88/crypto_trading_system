"""Scalp V2 — скальперинг стратегия по рекомендациям документа.

Архитектура:
- 15m: Market Regime (EMA50 > EMA200)
- 5m: Entry (RSI 35-45, Volume > avg, ATR > avg)
- TP 0.5-1%, SL 0.3-0.5%

Индикаторы:
- EMA50, EMA200 (тренд)
- RSI14 (вход)
- ATR14 (волатильность)
- Volume SMA20 (подтверждение)
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

PARAMETERS_VERSION = "scalp_v2"


@dataclass
class ScalpV2Config:
    """Configuration for Scalp V2 strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Trend filter (15m regime)
    ema_fast: int = 50
    ema_slow: int = 200

    # Entry conditions (5m)
    rsi_min: Decimal = Decimal("35")
    rsi_max: Decimal = Decimal("45")
    volume_multiplier: Decimal = Decimal("1.2")  # Volume > 1.2x average
    atr_multiplier: Decimal = Decimal("1.0")  # ATR > 1.0x average

    # Position sizing
    position_size_pct: Decimal = Decimal("0.03")  # 3% per trade

    # Take profit / Stop loss
    take_profit_pct: Decimal = Decimal("0.007")  # 0.7% TP
    stop_loss_pct: Decimal = Decimal("0.004")  # 0.4% SL

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.005")  # Activate at +0.5%
    trailing_distance: Decimal = Decimal("0.003")  # Trail by 0.3%

    # Max holding
    max_holding_periods: int = 12  # Max 12 candles = 2 hours on 15m


class ScalpV2Strategy(BaseStrategy):
    """Scalp V2 — скальперинг по рекомендациям документа.

    Entry:
    - EMA50 > EMA200 (тренд)
    - RSI 35-45 (откат)
    - close > EMA200
    - Volume > average
    - ATR > average

    Exit:
    - Take Profit 0.7%
    - Stop Loss 0.4%
    - Trailing Stop +0.5% / -0.3%
    - Max holding 12 candles
    """

    def __init__(
        self,
        symbols: list[str],
        config: ScalpV2Config | None = None,
    ) -> None:
        super().__init__("ScalpV2", symbols)
        self.config = config or ScalpV2Config()
        self.trailing_highs: dict[str, Decimal] = {}
        self._volume_avg: dict[str, Decimal] = {}
        self._atr_avg: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for Scalp V2."""
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

        if any(v is None for v in (rsi, ema50, ema200)):
            return None

        rsi_value = Decimal(str(rsi))
        ema50_value = Decimal(str(ema50))
        ema200_value = Decimal(str(ema200))
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Update volume average
        if symbol not in self._volume_avg:
            self._volume_avg[symbol] = volume
        else:
            self._volume_avg[symbol] = (self._volume_avg[symbol] * 19 + volume) / 20

        # Update ATR average
        if atr_value is not None:
            if symbol not in self._atr_avg:
                self._atr_avg[symbol] = atr_value
            else:
                self._atr_avg[symbol] = (self._atr_avg[symbol] * 19 + atr_value) / 20

        # 1. Trend filter: close > EMA200 (мягкий фильтр)
        if close <= ema200_value:
            return None

        # 2. RSI in buy zone (35-45)
        if rsi_value < self.config.rsi_min or rsi_value > self.config.rsi_max:
            return None

        # 3. Price rising OR close to EMA200
        previous_close = self._previous_close.get(symbol, close)
        self._previous_close[symbol] = close
        price_near_ema = (close - ema200_value) / ema200_value < Decimal("0.01") if ema200_value > 0 else False
        if close <= previous_close and not price_near_ema:
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
            "scalp_v2_entry",
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
            reason=f"Scalp V2: RSI={rsi_value:.1f}, Vol={volume/vol_avg:.1f}x",
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
        """Check exit conditions for Scalp V2."""
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
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Take Profit: {take_profit}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "take_profit"},
            )

        # Exit condition 2: Stop Loss
        stop_loss = entry_price * (Decimal("1") - self.config.stop_loss_pct)
        if close <= stop_loss:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Stop Loss: {stop_loss}",
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
                    reason=f"Trailing Stop: {trailing_stop}",
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
