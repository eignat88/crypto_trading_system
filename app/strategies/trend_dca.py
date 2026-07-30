from decimal import Decimal
from typing import Optional
from dataclasses import dataclass

from app.strategies.base_strategy import BaseStrategy, Signal
from app.indicators.market_regime import MarketRegimeDetector, MarketRegime


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
        config: DCAConfig = None,
    ):
        super().__init__("TrendDCA", symbols)
        self.config = config or DCAConfig()
        self.regime_detector = MarketRegimeDetector()
        self.dca_levels: dict[str, int] = {}  # Track DCA level per symbol

    def should_enter(
        self,
        candle: dict,
        indicators: dict,
        portfolio_state: dict,
    ) -> Optional[Signal]:
        """Check entry conditions for Trend DCA."""
        symbol = candle.get("symbol")
        close = candle.get("close")
        timestamp = candle.get("open_time")

        # Get indicators
        ema_200 = indicators.get("ema_200")
        ema_50 = indicators.get("ema_50")
        rsi = indicators.get("rsi")
        regime = indicators.get("regime")
        volatility = indicators.get("volatility")

        # Check if we have all required indicators
        if not all([ema_200, ema_50, rsi, regime]):
            return None

        # Check if we already have a position
        if portfolio_state.get("has_position", False):
            return None

        # Check regime
        if regime != MarketRegime.TREND_UP:
            return None

        # Check entry conditions
        if close <= ema_200:
            return None

        if ema_50 <= ema_200:
            return None

        if rsi > self.config.rsi_entry_threshold:
            return None

        # Check volatility (if available)
        if volatility and volatility > Decimal("0.8"):
            return None

        # Calculate position size (base order)
        capital = portfolio_state.get("capital", Decimal("0"))
        max_position_value = capital * self.config.max_capital_per_position
        quantity = max_position_value / close

        # Calculate stop loss (e.g., 5% below entry)
        stop_loss = close * Decimal("0.95")
        take_profit = close * (Decimal("1") + self.config.take_profit_pct)

        # Reset DCA level
        self.dca_levels[symbol] = 0

        return Signal(
            action="open_long",
            symbol=symbol,
            price=close,
            quantity=quantity,
            timestamp=timestamp,
            reason="Trend DCA base order",
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def should_exit(
        self,
        candle: dict,
        indicators: dict,
        position: dict,
    ) -> Optional[Signal]:
        """Check exit conditions for Trend DCA."""
        symbol = candle.get("symbol")
        close = candle.get("close")
        timestamp = candle.get("open_time")

        # Get position info
        entry_price = position.get("entry_price")
        side = position.get("side")
        quantity = position.get("quantity")
        unrealized_pnl_pct = position.get("unrealized_pnl_pct", Decimal("0"))

        # Get indicators
        regime = indicators.get("regime")
        ema_200 = indicators.get("ema_200")

        # Check holding period
        holding_periods = position.get("holding_periods", 0)
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

        # Check trailing stop
        if unrealized_pnl_pct >= self.config.trailing_stop_activation:
            trailing_stop = close * (Decimal("1") - self.config.trailing_stop_distance)
            if close <= trailing_stop:
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
        candle: dict,
        indicators: dict,
        position: dict,
    ) -> Optional[Signal]:
        """
        Check if we should add a DCA safety order.

        DCA is triggered when price drops by a certain percentage from entry.
        """
        symbol = candle.get("symbol")
        close = candle.get("close")
        timestamp = candle.get("open_time")

        entry_price = position.get("entry_price")
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

                capital = position.get("capital", Decimal("0"))
                dca_value = capital * dca_pct
                quantity = dca_value / close

                # Update DCA level
                self.dca_levels[symbol] = current_dca_level + 1

                return Signal(
                    action="open_long",
                    symbol=symbol,
                    price=close,
                    quantity=quantity,
                    timestamp=timestamp,
                    reason=f"DCA safety order {current_dca_level + 1}",
                )

        return None
