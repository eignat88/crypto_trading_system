"""Trend Pullback DCA v1 — гибкая стратегия для MVP.

Логика:
1. Определяем тренд (EMA50 > EMA200, close > EMA200)
2. Ждём откат (RSI 35-55, близость к EMA50)
3. Подтверждаем разворот (close > previous close)
4. Покупаем частями (DCA)
5. Выход по TP/SL или смене тренда

Scoring system:
- Каждое условие даёт 0-2 балла
- Вход при score >= 7 из 10
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

PARAMETERS_VERSION = "trend_pullback_dca_v1"


@dataclass
class TrendPullbackDCAConfig:
    """Configuration for Trend Pullback DCA v1."""

    parameters_version: str = PARAMETERS_VERSION

    # Trend filters
    ema_fast: int = 50
    ema_slow: int = 200

    # Entry conditions
    rsi_min: Decimal = Decimal("35")
    rsi_max: Decimal = Decimal("55")
    ema50_distance: Decimal = Decimal("0.03")  # 3% from EMA50
    min_score: int = 7  # out of 10

    # Volatility filter
    atr_min_pct: Decimal = Decimal("0.005")  # 0.5%
    atr_max_pct: Decimal = Decimal("0.05")  # 5%

    # Allowed regimes
    allowed_regimes: tuple[str, ...] = ("TREND_UP", "TREND_RECOVERY")

    # Position sizing
    base_order_pct: Decimal = Decimal("0.25")
    max_capital_per_position: Decimal = Decimal("0.10")

    # Exit conditions
    take_profit_pct: Decimal = Decimal("0.05")
    stop_loss_pct: Decimal = Decimal("0.03")
    trailing_stop_activation: Decimal = Decimal("0.03")
    trailing_stop_distance: Decimal = Decimal("0.02")
    max_holding_periods: int = 100


class TrendPullbackDCAStrategy(BaseStrategy):
    """Trend Pullback DCA v1 — flexible entry with scoring system.

    Entry conditions (score-based):
    1. close > EMA200 (0-2 pts)
    2. EMA50 > EMA200 (0-2 pts)
    3. 35 <= RSI14 <= 55 (0-2 pts)
    4. close <= EMA50 * 1.03 (0-2 pts)
    5. current_close > previous_close (0-1 pt)
    6. 0.5% < ATR14/close < 5% (0-1 pt)
    7. regime IN (TREND_UP, TREND_RECOVERY) (0-1 pt)

    Total: 0-10 points, entry at score >= min_score
    """

    def __init__(
        self,
        symbols: list[str],
        config: TrendPullbackDCAConfig | None = None,
    ) -> None:
        super().__init__("TrendPullbackDCA", symbols)
        self.config = config or TrendPullbackDCAConfig()
        self.trailing_highs: dict[str, Decimal] = {}
        self._previous_close: dict[str, Decimal] = {}

    def _score_entry(
        self,
        close: Decimal,
        ema50: Decimal,
        ema200: Decimal,
        rsi: Decimal,
        atr: Decimal | None,
        regime: Any,
        previous_close: Decimal | None,
    ) -> tuple[int, list[str]]:
        """Calculate entry score (0-10)."""
        score = 0
        reasons = []

        # 1. close > EMA200 (0-2 pts)
        if close > ema200:
            score += 2
            reasons.append("close>EMA200")
        elif close > ema200 * Decimal("0.98"):
            score += 1
            reasons.append("close~EMA200")

        # 2. EMA50 > EMA200 (0-2 pts)
        if ema50 > ema200:
            score += 2
            reasons.append("EMA50>EMA200")
        elif ema50 > ema200 * Decimal("0.99"):
            score += 1
            reasons.append("EMA50~EMA200")

        # 3. RSI in range 35-55 (0-2 pts)
        if self.config.rsi_min <= rsi <= self.config.rsi_max:
            score += 2
            reasons.append(f"RSI={rsi:.1f}")
        elif Decimal("30") <= rsi <= Decimal("60"):
            score += 1
            reasons.append(f"RSI~{rsi:.1f}")

        # 4. close <= EMA50 * 1.03 (0-2 pts)
        ema50_upper = ema50 * (Decimal("1") + self.config.ema50_distance)
        if close <= ema50:
            score += 2
            reasons.append("close<=EMA50")
        elif close <= ema50_upper:
            score += 1
            reasons.append("close<=EMA50*1.03")

        # 5. current_close > previous_close (0-1 pt)
        if previous_close is not None and close > previous_close:
            score += 1
            reasons.append("close>prev_close")

        # 6. ATR in range 0.5%-5% (0-1 pt)
        if atr is not None and close > 0:
            atr_pct = atr / close
            if self.config.atr_min_pct <= atr_pct <= self.config.atr_max_pct:
                score += 1
                reasons.append(f"ATR={atr_pct:.2%}")

        # 7. regime allowed (0-1 pt)
        regime_str = str(regime) if regime else ""
        if regime_str in self.config.allowed_regimes:
            score += 1
            reasons.append(f"regime={regime_str}")

        return score, reasons

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions with scoring system."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        ema200 = indicators.get("ema_200")
        ema50 = indicators.get("ema_50")
        rsi = indicators.get("rsi")
        regime = indicators.get("regime")
        atr = indicators.get("atr")

        if any(v is None for v in (ema200, ema50, rsi, regime)):
            return None

        ema200_value = Decimal(str(ema200))
        ema50_value = Decimal(str(ema50))
        rsi_value = Decimal(str(rsi))
        atr_value = Decimal(str(atr)) if atr is not None else None

        # No position check
        if portfolio_state.get("has_position", False):
            return None

        # Get previous close for reversal confirmation
        previous_close = self._previous_close.get(symbol)

        # Calculate score
        score, reasons = self._score_entry(
            close=close,
            ema50=ema50_value,
            ema200=ema200_value,
            rsi=rsi_value,
            atr=atr_value,
            regime=regime,
            previous_close=previous_close,
        )

        # Update previous close for next candle
        self._previous_close[symbol] = close

        # Log scoring
        logger.debug(
            "entry_score_calculated",
            symbol=symbol,
            score=score,
            min_score=self.config.min_score,
            reasons=reasons,
        )

        # Check if score meets threshold
        if score < self.config.min_score:
            return None

        # Calculate position size
        capital = Decimal(str(portfolio_state.get("capital", "0")))
        max_position_value = capital * self.config.max_capital_per_position
        base_order_value = max_position_value * self.config.base_order_pct
        quantity = base_order_value / close

        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason=f"Score {score}/10: {', '.join(reasons)}",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            parameters_version=self.config.parameters_version,
            regime=str(regime),
            indicators=indicators,
            metadata={
                "dca_level": 0,
                "score": score,
                "reasons": reasons,
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
        unrealized_pnl_pct = Decimal(str(position.get("unrealized_pnl_pct", "0")))
        regime = indicators.get("regime")
        regime_value = None if regime is None else str(regime)

        # Max holding period
        holding_periods = int(position.get("holding_periods", 0))
        if holding_periods >= self.config.max_holding_periods:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason="Max holding period reached",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                regime=regime_value,
            )

        # Regime change to downtrend
        if regime and regime == MarketRegime.TREND_DOWN:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason="Regime changed to TREND_DOWN",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                regime=regime_value,
            )

        # Trailing stop
        activation_price = entry_price * (Decimal("1") + self.config.trailing_stop_activation)
        trailing_high = self.trailing_highs.get(symbol)
        if trailing_high is not None or high >= activation_price:
            trailing_high = max(trailing_high or high, high)
            self.trailing_highs[symbol] = trailing_high
            trailing_stop = trailing_high * (Decimal("1") - self.config.trailing_stop_distance)
            if low <= trailing_stop:
                self.trailing_highs.pop(symbol, None)
                return Signal(
                    action="close",
                    symbol=symbol,
                    price=trailing_stop,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason="Trailing stop hit",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    regime=regime_value,
                    metadata={"exit_source": "trailing_stop"},
                )

        # Take profit
        if unrealized_pnl_pct >= self.config.take_profit_pct:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason="Take profit hit",
                strategy=self.name,
                parameters_version=self.config.parameters_version,
                indicators=indicators,
                regime=regime_value,
            )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update fill-dependent strategy state."""
        level = signal.metadata.get("dca_level")
        if isinstance(level, int):
            if level == 0:
                self.trailing_highs.pop(signal.symbol, None)
