from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.indicators.market_regime import MarketRegime, MarketRegimeDetector
from app.models import Fill, Signal
from app.strategies.base_strategy import BaseStrategy


@dataclass
class DCAConfig:
    """DCA configuration."""
    # Position allocation percentages
    base_order_pct: Decimal = Decimal("0.25")  # 25%
    safety_order_1_pct: Decimal = Decimal("0.20")  # 20%
    safety_order_2_pct: Decimal = Decimal("0.25")  # 25%
    safety_order_3_pct: Decimal = Decimal("0.30")  # 30%

    # Entry conditions
    rsi_entry_threshold: Decimal = Decimal("45")
    max_positions: int = 1

    # Exit conditions
    take_profit_pct: Decimal = Decimal("0.05")  # 5%
    stop_loss_pct: Decimal = Decimal("0.15")  # 15%; sized risk remains <= 0.5%
    trailing_stop_activation: Decimal = Decimal("0.03")  # 3%
    trailing_stop_distance: Decimal = Decimal("0.02")  # 2%
    max_holding_periods: int = 100  # candles

    # Risk limits
    max_capital_per_position: Decimal = Decimal("0.10")  # 10% of capital


class TrendDCAStrategy(BaseStrategy):
    """
    Trend DCA Strategy.

    Entry conditions:
    - close > EMA200
    - EMA50 > EMA200
    - RSI <= 45
    - market_regime = TREND_UP
    - No open position
    - Volatility below critical level

    Position structure:
    - Base order: 25%
    - Safety order 1: 20%
    - Safety order 2: 25%
    - Safety order 3: 30%
    """

    def __init__(
        self,
        symbols: list[str],
        config: DCAConfig | None = None,
    ):
        super().__init__("TrendDCA", symbols)
        self.config = config or DCAConfig()
        self.regime_detector = MarketRegimeDetector()
        self.dca_levels: dict[str, int] = {}  # Track DCA level per symbol
        self.trailing_highs: dict[str, Decimal] = {}

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """Check entry conditions for Trend DCA."""
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        # Get indicators
        ema_200 = indicators.get("ema_200")
        ema_50 = indicators.get("ema_50")
        rsi = indicators.get("rsi")
        regime = indicators.get("regime")
        volatility = indicators.get("volatility")

        # Check if we have all required indicators
        if any(value is None for value in (ema_200, ema_50, rsi, regime)):
            return None
        ema_200_value = Decimal(str(ema_200))
        ema_50_value = Decimal(str(ema_50))
        rsi_value = Decimal(str(rsi))

        # Check if we already have a position
        if portfolio_state.get("has_position", False):
            return None

        # Check regime
        if regime != MarketRegime.TREND_UP:
            return None

        # Check entry conditions
        if close <= ema_200_value:
            return None

        if ema_50_value <= ema_200_value:
            return None

        if rsi_value > self.config.rsi_entry_threshold:
            return None

        # Check volatility (if available)
        if volatility is not None and Decimal(str(volatility)) > Decimal("0.8"):
            return None

        # Calculate position size (base order)
        capital = Decimal(str(portfolio_state.get("capital", "0")))
        max_position_value = capital * self.config.max_capital_per_position
        base_order_value = max_position_value * self.config.base_order_pct
        quantity = base_order_value / close

        # The base order is 2.5% of capital by default, so a wider stop can
        # coexist with the 3/5/8% DCA ladder while remaining below 0.5% risk.
        stop_loss = close * (Decimal("1") - self.config.stop_loss_pct)
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)

        # Reset DCA level
        self.dca_levels[symbol] = 0
        self.trailing_highs.pop(symbol, None)

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason="Trend DCA base order",
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=self.name,
            regime=str(regime),
            indicators=indicators,
            metadata={"dca_level": 0},
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
        high = Decimal(str(candle.get("high", close)))
        low = Decimal(str(candle.get("low", close)))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        # Get position info
        entry_price = Decimal(str(position["entry_price"]))
        quantity = Decimal(str(position["quantity"]))
        unrealized_pnl_pct = Decimal(str(position.get("unrealized_pnl_pct", "0")))

        # Get indicators
        regime = indicators.get("regime")
        # Check holding period
        holding_periods = int(position.get("holding_periods", 0))
        if holding_periods >= self.config.max_holding_periods:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason="Max holding period reached",
            )

        # Check regime change
        if regime and regime == MarketRegime.TREND_DOWN:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason="Regime changed to TREND_DOWN",
            )

        # Once activated, trail the highest observed close instead of the current
        # close (which can never be below a percentage of itself).
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
                    price=close,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason="Trailing stop hit",
                )

        # Check take profit
        if unrealized_pnl_pct >= self.config.take_profit_pct:
            return Signal(
                action="close",
                symbol=symbol,
                price=close,
                quantity=quantity,
                timestamp=timestamp,
                reason="Take profit hit",
            )

        return None

    def should_add_dca(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """
        Check if we should add a DCA safety order.

        DCA is triggered when price drops by a certain percentage from entry.
        """
        symbol = str(candle["symbol"])
        close = Decimal(str(candle["close"]))
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        entry_price = Decimal(str(position["entry_price"]))
        current_dca_level = self.dca_levels.get(symbol, 0)

        # Check if we can add more DCA levels
        if current_dca_level >= 3:
            return None

        # Calculate price drop from entry
        price_drop = (entry_price - close) / entry_price

        # DCA levels: 3%, 5%, 8% drops
        dca_thresholds = [
            Decimal("0.03"),
            Decimal("0.05"),
            Decimal("0.08"),
        ]

        if current_dca_level < len(dca_thresholds):
            threshold = dca_thresholds[current_dca_level]
            if price_drop >= threshold:
                # Calculate DCA quantity based on level
                dca_pcts = [
                    self.config.safety_order_1_pct,
                    self.config.safety_order_2_pct,
                    self.config.safety_order_3_pct,
                ]
                dca_pct = dca_pcts[current_dca_level]

                capital = Decimal(str(position.get("capital", "0")))
                max_position_value = capital * self.config.max_capital_per_position
                dca_value = max_position_value * dca_pct
                quantity = dca_value / close

                return Signal(
                    action="open_long",
                    symbol=symbol,
                    price=close,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason=f"DCA safety order {current_dca_level + 1}",
                    strategy=self.name,
                    indicators=indicators,
                    metadata={"dca_level": current_dca_level + 1},
                )

        return None

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Advance DCA state only when the corresponding order was filled."""
        level = signal.metadata.get("dca_level")
        if isinstance(level, int):
            self.dca_levels[signal.symbol] = level
