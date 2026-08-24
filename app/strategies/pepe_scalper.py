"""PEPE Scalper — скальперинг для PEPEUSDT на 15m свечах.

Логика:
1. Входим при RSI < 35 + рост цены + close > EMA20
2. Выходим по TP 3% или trailing stop
3. Tight SL 1.5%
4. Быстрые сделки (1-4 свечи = 15-60 минут)

Особенности:
- Малые позиции (3% капитала)
- Быстрые выходы
- TP 3%, SL 1.5%
- 20-50 сделок за 10 дней
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

PARAMETERS_VERSION = "pepe_scalper_v1"


@dataclass
class PEPEScalperConfig:
    """Configuration for PEPE Scalper strategy."""

    parameters_version: str = PARAMETERS_VERSION

    # Entry conditions
    rsi_buy_level: Decimal = Decimal("45")  # Buy when RSI < 45 (откат)
    rsi_sell_level: Decimal = Decimal("55")  # Sell when RSI > 55

    # Position sizing
    position_size_pct: Decimal = Decimal("0.03")  # 3% per trade

    # Take profit / Stop loss
    take_profit_pct: Decimal = Decimal("0.05")  # 5% TP (шире)
    stop_loss_pct: Decimal = Decimal("0.02")  # 2% SL

    # Trailing stop
    trailing_activation: Decimal = Decimal("0.03")  # Activate at +3%
    trailing_distance: Decimal = Decimal("0.015")  # Trail by 1.5%

    # Filters
    min_atr_pct: Decimal = Decimal("0.002")
    max_atr_pct: Decimal = Decimal("0.010")

    # Trend filter
    ema_fast: int = 20
    ema_slow: int = 50


class PEPEScalperStrategy(BaseStrategy):
    """PEPE Scalper — быстрые сделки на 15m свечах.

    Entry:
    - RSI < 35 (перепроданность)
    - close > EMA20 (рост)
    - close > previous_close (подтверждение)

    Exit:
    - RSI > 65 (перекупленность)
    - Take Profit 3%
    - Stop Loss 1.5%
    - Trailing Stop +2% / -1%
    """

    def __init__(
        self,
        symbols: list[str],
        config: PEPEScalperConfig | None = None,
    ) -> None:
        super().__init__("PEPEScalper", symbols)
        self.config = config or PEPEScalperConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}
        self._trade_count: dict[str, int] = {s: 0 for s in symbols}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for PEPE scalping."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        rsi = indicators.get("rsi")
        ema20 = indicators.get("ema_20")
        atr = indicators.get("atr")

        if rsi is None or ema20 is None:
            return None

        rsi_value = Decimal(str(rsi))
        ema20_value = Decimal(str(ema20))
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Get previous close
        previous_close = self._previous_close.get(symbol, close)
        self._previous_close[symbol] = close

        # Entry conditions
        # 1. RSI in buy zone (35-45)
        if rsi_value < Decimal("35") or rsi_value > self.config.rsi_buy_level:
            return None

        # 2. Price above EMA20
        if close <= ema20_value:
            return None

        # 3. Price rising OR close to EMA20 (potential bounce)
        price_near_ema = (close - ema20_value) / ema20_value < Decimal("0.01")
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
            "pepe_scalp_entry",
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
            reason=f"PEPE Scalp: RSI={rsi_value:.1f}, TP={take_profit:.8f}",
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
        """Check exit conditions for PEPE scalping."""
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
        if rsi_value > self.config.rsi_sell_level:
            logger.info("pepe_scalp_exit_rsi", symbol=symbol, rsi=float(rsi_value))
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason=f"Exit: RSI={rsi_value:.1f} > {self.config.rsi_sell_level}",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                metadata={"exit_source": "rsi_overbought"},
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
                reason=f"Take Profit: {take_profit:.8f}",
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
                reason=f"Stop Loss: {stop_loss:.8f}",
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
                    reason=f"Trailing Stop: {trailing_stop:.8f}",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    metadata={"exit_source": "trailing_stop"},
                )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        pass
