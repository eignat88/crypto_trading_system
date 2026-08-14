from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from app.indicators.market_regime import MarketRegime
from app.models import Signal
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy

EXPERIMENT_PARAMETERS_VERSION = "trend_dca_v1_trend_down_confirm3"
TREND_DOWN_CONFIRMATION_BARS = 3


class TrendDCAConfirm3Strategy(TrendDCAStrategy):
    """TrendDCA experiment requiring 3 consecutive TREND_DOWN bars to exit.

    This class intentionally changes only the market-regime exit rule from the
    baseline ``TrendDCAStrategy``. Entry, DCA, take-profit, stop-loss, trailing,
    max holding, position sizing, and fill-state handling are inherited unchanged.
    """

    def __init__(self, symbols: list[str]) -> None:
        super().__init__(
            symbols=symbols,
            config=DCAConfig(parameters_version=EXPERIMENT_PARAMETERS_VERSION),
        )
        self.trend_down_streaks: dict[str, int] = {}

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """Apply baseline exits with a 3-bar confirmation for TREND_DOWN only."""
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

        holding_periods = int(position.get("holding_periods", 0))
        if holding_periods >= self.config.max_holding_periods:
            self.trend_down_streaks.pop(symbol, None)
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

        if regime == MarketRegime.TREND_DOWN:
            streak = self.trend_down_streaks.get(symbol, 0) + 1
            self.trend_down_streaks[symbol] = streak
            if streak >= TREND_DOWN_CONFIRMATION_BARS:
                self.trend_down_streaks.pop(symbol, None)
                return Signal(
                    action="close",
                    symbol=symbol,
                    price=close,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason="TREND_DOWN confirmed for 3 consecutive bars",
                    strategy=self.name,
                    parameters_version=self.config.parameters_version,
                    indicators=indicators,
                    regime=regime_value,
                    metadata={
                        "experiment": "trend_down_confirmation",
                        "confirmation_bars": TREND_DOWN_CONFIRMATION_BARS,
                    },
                )
        else:
            self.trend_down_streaks.pop(symbol, None)

        activation_price = entry_price * (
            Decimal("1") + self.config.trailing_stop_activation
        )
        trailing_high = self.trailing_highs.get(symbol)
        if trailing_high is not None or high >= activation_price:
            trailing_high = max(trailing_high or high, high)
            self.trailing_highs[symbol] = trailing_high
            trailing_stop = trailing_high * (
                Decimal("1") - self.config.trailing_stop_distance
            )
            if low <= trailing_stop:
                self.trailing_highs.pop(symbol, None)
                self.trend_down_streaks.pop(symbol, None)
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

        if unrealized_pnl_pct >= self.config.take_profit_pct:
            self.trend_down_streaks.pop(symbol, None)
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
