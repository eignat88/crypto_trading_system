"""BTC Trend Pullback DCA v1 — оптимальная стратегия для текущего рынка.

Логика:
1. Определяем сильный тренд (EMA50 > EMA200, close > EMA200)
2. Ждём откат (RSI < 55, волатильность снижается)
3. Покупаем частями (DCA) на 4 уровнях
4. Выход по TP или trailing stop

Уровни входа:
- L1: 74,900 (-3%) — 15% капитала
- L2: 72,500 (-6%) — 25% капитала
- L3: 70,000 (-9%) — 30% капитала
- L4: 67,100 (-13%) — 30% капитала

Цели:
- TP1: 82,000 (+6%)
- TP2: 87,000 (+13%)
- TP3: 92,000 (+19%)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from app.indicators.market_regime import MarketRegime
from app.models import Fill, Signal
from app.strategies.base_strategy import BaseStrategy

logger = structlog.get_logger()

PARAMETERS_VERSION = "btc_trend_pullback_dca_v1"


@dataclass
class BTCTrendPullbackDCAConfig:
    """Configuration for BTC Trend Pullback DCA v1."""

    parameters_version: str = PARAMETERS_VERSION

    # DCA levels (optimized parameters)
    # Best config: 3 levels, 5% capital, RSI<55, ATR<0.8%
    dca_levels: list[dict[str, Any]] = field(default_factory=lambda: [
        {"level": 1, "price_pct": Decimal("-0.03"), "capital_pct": Decimal("0.05"), "rsi_max": Decimal("55"), "atr_max": Decimal("0.008")},
        {"level": 2, "price_pct": Decimal("-0.06"), "capital_pct": Decimal("0.05"), "rsi_max": Decimal("55"), "atr_max": Decimal("0.008")},
        {"level": 3, "price_pct": Decimal("-0.09"), "capital_pct": Decimal("0.05"), "rsi_max": Decimal("55"), "atr_max": Decimal("0.008")},
    ])

    # Take profit levels (optimized: 5%, 10%, 15%)
    tp_levels: list[dict[str, Any]] = field(default_factory=lambda: [
        {"level": 1, "price_pct": Decimal("0.05"), "sell_pct": Decimal("0.30")},
        {"level": 2, "price_pct": Decimal("0.10"), "sell_pct": Decimal("0.30")},
        {"level": 3, "price_pct": Decimal("0.15"), "sell_pct": Decimal("0.40")},
    ])

    # Stop loss (optimized: 10%)
    soft_sl_pct: Decimal = Decimal("-0.10")  # -10%
    hard_sl_pct: Decimal = Decimal("-0.13")  # -13% (10% * 1.3)

    # Trailing stop
    trailing_activation_pct: Decimal = Decimal("0.05")  # activate at +5%
    trailing_distance_pct: Decimal = Decimal("0.03")  # trail by 3%

    # Trend filters
    ema_fast: int = 50
    ema_slow: int = 200

    # Risk limits
    max_daily_loss_pct: Decimal = Decimal("0.02")
    max_drawdown_pct: Decimal = Decimal("0.10")


class BTCTrendPullbackDCAStrategy(BaseStrategy):
    """BTC Trend Pullback DCA v1 — multi-level DCA with scoring.

    Entry conditions:
    1. close > EMA200 (trend)
    2. EMA50 > EMA200 (trend confirmation)
    3. RSI < level_max (pullback)
    4. ATR < level_max (volatility normalization)
    5. close <= EMA50 * 1.03 (proximity to support)
    """

    def __init__(
        self,
        symbols: list[str],
        config: BTCTrendPullbackDCAConfig | None = None,
    ) -> None:
        super().__init__("BTCTrendPullbackDCA", symbols)
        self.config = config or BTCTrendPullbackDCAConfig()
        self.dca_levels_filled: dict[str, set[int]] = {s: set() for s in symbols}
        self.tp_levels_filled: dict[str, set[int]] = {s: set() for s in symbols}
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._entry_prices: dict[str, list[Decimal]] = {s: [] for s in symbols}
        self._position_value: dict[str, Decimal] = {s: Decimal("0") for s in symbols}

    def _calculate_avg_entry(self, symbol: str) -> Decimal:
        """Calculate average entry price."""
        prices = self._entry_prices.get(symbol, [])
        if not prices:
            return Decimal("0")
        return sum(prices) / Decimal(str(len(prices)))

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for each DCA level."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        ema200 = indicators.get("ema_200")
        ema50 = indicators.get("ema_50")
        rsi = indicators.get("rsi")
        atr = indicators.get("atr")

        if any(v is None for v in (ema200, ema50, rsi)):
            return None

        ema200_value = Decimal(str(ema200))
        ema50_value = Decimal(str(ema50))
        rsi_value = Decimal(str(rsi))
        atr_value = Decimal(str(atr)) if atr is not None else None

        # Trend check — only enter in uptrend
        if close <= ema200_value or ema50_value <= ema200_value:
            return None

        # Check each DCA level
        for level_config in self.config.dca_levels:
            level_num = level_config["level"]
            if level_num in self.dca_levels_filled.get(symbol, set()):
                continue

            # Price must be within range (close to or below EMA50)
            ema50_distance = (close - ema50_value) / ema50_value
            if ema50_distance > Decimal("0.03"):  # More than 3% above EMA50
                continue

            rsi_max = level_config["rsi_max"]
            atr_max = level_config["atr_max"]

            # Check RSI condition
            if rsi_value > rsi_max:
                continue

            # Check ATR condition (relaxed)
            if atr_value is not None:
                atr_pct = atr_value / close
                if atr_pct > atr_max:
                    continue

            # Calculate position size
            capital = Decimal(str(portfolio_state.get("capital", "0")))
            level_amount = capital * level_config["capital_pct"]
            quantity = level_amount / close

            # Log entry
            logger.info(
                "dca_level_entry",
                symbol=symbol,
                level=level_num,
                price=float(close),
                rsi=float(rsi_value),
                atr_pct=float(atr_value / close) if atr_value else None,
                amount=float(level_amount),
            )

            # Mark level as filled
            self.dca_levels_filled[symbol].add(level_num)
            self._entry_prices[symbol].append(close)
            self._position_value[symbol] += level_amount

            return Signal(
                action="open_long",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"DCA Level {level_num}: RSI={rsi_value:.1f}, ATR={atr_value/close:.2%}" if atr_value else f"DCA Level {level_num}: RSI={rsi_value:.1f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                regime=str(indicators.get("regime")),
                indicators=indicators,
                metadata={
                    "dca_level": level_num,
                    "capital_pct": float(level_config["capital_pct"]),
                },
            )

        return None

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
        unrealized_pnl_pct = Decimal(str(position.get("unrealized_pnl_pct", "0")))

        # Calculate average entry
        avg_entry = self._calculate_avg_entry(symbol)
        if avg_entry == 0:
            avg_entry = entry_price

        # Check take profit levels
        for tp_config in self.config.tp_levels:
            tp_level = tp_config["level"]
            if tp_level in self.tp_levels_filled.get(symbol, set()):
                continue

            tp_price = avg_entry * (Decimal("1") + tp_config["price_pct"])
            if close >= tp_price:
                sell_pct = tp_config["sell_pct"]
                sell_qty = quantity * sell_pct

                logger.info(
                    "take_profit_hit",
                    symbol=symbol,
                    level=tp_level,
                    price=float(close),
                    tp_price=float(tp_price),
                    sell_pct=float(sell_pct),
                )

                self.tp_levels_filled[symbol].add(tp_level)

                return Signal(
                    action="close",
                    symbol=symbol,
                    price=close,
                    quantity=sell_qty,
                    timestamp=timestamp,
                    reason=f"TP{tp_level} hit: {tp_price:.0f}",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    metadata={"tp_level": tp_level, "sell_pct": float(sell_pct)},
                )

        # Check soft stop loss
        soft_sl_price = avg_entry * (Decimal("1") + self.config.soft_sl_pct)
        if close <= soft_sl_price:
            logger.warning("soft_stop_loss_hit", symbol=symbol, price=float(close), sl=float(soft_sl_price))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity * Decimal("0.5"),  # Sell 50%
                timestamp=timestamp,
                reason=f"Soft SL: {soft_sl_price:.0f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"stop_type": "soft"},
            )

        # Check hard stop loss
        hard_sl_price = avg_entry * (Decimal("1") + self.config.hard_sl_pct)
        if close <= hard_sl_price:
            logger.warning("hard_stop_loss_hit", symbol=symbol, price=float(close), sl=float(hard_sl_price))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Hard SL: {hard_sl_price:.0f}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"stop_type": "hard"},
            )

        # Trailing stop
        activation_price = avg_entry * (Decimal("1") + self.config.trailing_activation_pct)
        trailing_high = self.trailing_highs.get(symbol)

        if trailing_high is not None or high >= activation_price:
            trailing_high = max(trailing_high or high, high)
            self.trailing_highs[symbol] = trailing_high
            trailing_stop = trailing_high * (Decimal("1") - self.config.trailing_distance_pct)

            if low <= trailing_stop:
                self.trailing_highs.pop(symbol, None)
                logger.info("trailing_stop_hit", symbol=symbol, price=float(close), trailing_stop=float(trailing_stop))
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

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
