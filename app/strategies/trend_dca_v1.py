"""Trend DCA V1 — стратегия для трендового рынка.

Логика:
1. Определяем тренд (EMA50 > EMA200, ADX > 20)
2. Ждём откат (-2% от максимума)
3. Покупаем частями (DCA)
4. Выход по TP 3-5% или пробою EMA50

Преимущества:
- Не пытается ловить каждую свечу
- Покупает только сильный рынок
- DCA снижает среднюю цену входа
- Комиссии меньше влияют на прибыль
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

PARAMETERS_VERSION = "trend_dca_v1"


@dataclass
class TrendDCAConfig:
    """Configuration for Trend DCA V1 strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Trend filters
    ema_fast: int = 50
    ema_slow: int = 200
    min_trend_strength: Decimal = Decimal("0.002")  # 0.2% min EMA distance

    # Entry conditions
    pullback_pct: Decimal = Decimal("0.015")  # 1.5% pullback from local high
    rsi_min: Decimal = Decimal("30")
    rsi_max: Decimal = Decimal("50")

    # DCA configuration
    dca_steps: int = 3
    dca_drop_1: Decimal = Decimal("0.03")  # First DCA at -3%
    dca_drop_2: Decimal = Decimal("0.05")  # Second DCA at -5%
    dca_allocation_1: Decimal = Decimal("0.30")  # 30% first entry
    dca_allocation_2: Decimal = Decimal("0.30")  # 30% second entry
    dca_allocation_3: Decimal = Decimal("0.40")  # 40% third entry

    # Position limits
    max_position_pct: Decimal = Decimal("0.10")  # 10% max position

    # Exit conditions
    take_profit_pct: Decimal = Decimal("0.05")  # 5% TP
    stop_loss_pct: Decimal = Decimal("0.08")  # 8% SL

    # Trend exit
    ema_exit_cross: bool = True  # Exit if EMA50 crosses below EMA200


class TrendDCAStrategy(BaseStrategy):
    """Trend DCA V1 — стратегия для трендового рынка.

    Entry:
    - EMA50 > EMA200 (тренд)
    - close > EMA200
    - Price -2% from local high (откат)
    - RSI 35-45

    DCA:
    - 1st entry: 30% at -3%
    - 2nd entry: 30% at -5%
    - 3rd entry: 40% at -8%

    Exit:
    - Take Profit 5%
    - Stop Loss 8%
    - EMA50 crosses below EMA200
    """

    def __init__(
        self,
        symbols: list[str],
        config: TrendDCAConfig | None = None,
    ) -> None:
        super().__init__("TrendDCA_V1", symbols)
        self.config = config or TrendDCAConfig()
        self.local_highs: dict[str, Decimal] = {}
        self.dca_entries: dict[str, int] = {}
        self.avg_entry_prices: dict[str, Decimal] = {}
        self.total_quantities: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for Trend DCA."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        high = Decimal(str(candle.get("high", close)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema50 = indicators.get("ema_50")
        ema200 = indicators.get("ema_200")

        if any(v is None for v in (rsi, ema50, ema200)):
            return None

        rsi_value = Decimal(str(rsi))
        ema50_value = Decimal(str(ema50))
        ema200_value = Decimal(str(ema200))

        # Update local high
        current_high = self.local_highs.get(symbol, high)
        if high > current_high:
            self.local_highs[symbol] = high
            current_high = high

        # Current DCA level
        current_dca = self.dca_entries.get(symbol, 0)

        # Exit if all DCA levels filled
        if current_dca >= self.config.dca_steps:
            return None

        # Trend filter: EMA50 > EMA200
        if ema50_value <= ema200_value:
            return None

        # Price above EMA200
        if close <= ema200_value:
            return None

        # Trend strength
        if ema200_value > 0:
            trend_strength = (ema50_value - ema200_value) / ema200_value
            if trend_strength < self.config.min_trend_strength:
                return None

        # Pullback condition
        pullback = (current_high - close) / current_high
        target_pullback = self.config.pullback_pct * (current_dca + 1)

        if pullback < target_pullback:
            return None

        # RSI condition
        if rsi_value < self.config.rsi_min or rsi_value > self.config.rsi_max:
            return None

        # Position size calculation
        capital = Decimal(str(portfolio_state.get("capital", "1000")))
        max_position = capital * self.config.max_position_pct
        current_position_value = self._position_value(symbol, close)

        # Determine allocation
        if current_dca == 0:
            allocation = self.config.dca_allocation_1
        elif current_dca == 1:
            allocation = self.config.dca_allocation_2
        else:
            allocation = self.config.dca_allocation_3

        position_value = max_position * allocation
        quantity = position_value / close

        # Check if we have enough capital
        if current_position_value + position_value > max_position:
            return None

        self._trade_count[symbol] = self._trade_count.get(symbol, 0) + 1
        self.dca_entries[symbol] = current_dca + 1

        # Update average entry price
        if symbol not in self.avg_entry_prices:
            self.avg_entry_prices[symbol] = close
            self.total_quantities[symbol] = quantity
        else:
            total_value = self.avg_entry_prices[symbol] * self.total_quantities[symbol]
            self.avg_entry_prices[symbol] = (total_value + position_value) / (self.total_quantities[symbol] + quantity)
            self.total_quantities[symbol] += quantity

        logger.info(
            "trend_dca_entry",
            symbol=symbol,
            price=float(close),
            dca_level=current_dca + 1,
            pullback=float(pullback),
            rsi=float(rsi_value),
            avg_entry=float(self.avg_entry_prices[symbol]),
            trade_num=self._trade_count[symbol],
        )

        # Calculate stop loss and take profit
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason=f"Trend DCA L{current_dca + 1}: Pullback={pullback:.1%}, RSI={rsi_value:.1f}",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(indicators.get("regime")),
            indicators=indicators,
            metadata={
                "dca_level": current_dca + 1,
                "pullback": float(pullback),
                "rsi": float(rsi_value),
                "avg_entry": float(self.avg_entry_prices[symbol]),
            },
        )

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Check exit conditions for Trend DCA."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        entry_price = Decimal(str(position["entry_price"]))
        quantity = Decimal(str(position["quantity"]))
        avg_entry = self.avg_entry_prices.get(symbol, entry_price)

        ema50 = indicators.get("ema_50")
        ema200 = indicators.get("ema_200")

        if ema50 is None or ema200 is None:
            return None

        ema50_value = Decimal(str(ema50))
        ema200_value = Decimal(str(ema200))

        # Exit condition 1: Take Profit
        take_profit = avg_entry * (Decimal("1") + self.config.take_profit_pct)
        if close >= take_profit:
            logger.info("trend_dca_exit_tp", symbol=symbol, price=float(close), tp=float(take_profit))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Take Profit: {take_profit:.2f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "take_profit", "avg_entry": float(avg_entry)},
            )

        # Exit condition 2: Stop Loss
        stop_loss = avg_entry * (Decimal("1") - self.config.stop_loss_pct)
        if close <= stop_loss:
            logger.info("trend_dca_exit_sl", symbol=symbol, price=float(close), sl=float(stop_loss))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Stop Loss: {stop_loss:.2f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "stop_loss", "avg_entry": float(avg_entry)},
            )

        # Exit condition 3: Trend reversal
        if self.config.ema_exit_cross and ema50_value < ema200_value:
            logger.info("trend_dca_exit_trend", symbol=symbol)
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Trend reversal: EMA50 < EMA200",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "trend_reversal", "avg_entry": float(avg_entry)},
            )

        return None

    def _position_value(self, symbol: str, current_price: Decimal) -> Decimal:
        """Calculate current position value."""
        qty = self.total_quantities.get(symbol, Decimal("0"))
        return qty * current_price

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
