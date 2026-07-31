from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from app.models import Fill, Signal


class BaseStrategy(ABC):
    """Base class for trading strategies."""

    def __init__(self, name: str, symbols: list[str]):
        self.name = name
        self.symbols = symbols
        self.state: dict[str, Any] = {}

    @abstractmethod
    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        """
        Determine if we should enter a position.

        Args:
            candle: Current candle data
            indicators: Calculated indicators
            portfolio_state: Current portfolio state

        Returns:
            Signal to enter or None
        """
        ...

    @abstractmethod
    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        """
        Determine if we should exit a position.

        Args:
            candle: Current candle data
            indicators: Calculated indicators
            position: Current position data

        Returns:
            Signal to exit or None
        """
        ...

    def calculate_position_size(
        self,
        capital: Decimal,
        risk_per_trade: Decimal,
        entry_price: Decimal,
        stop_loss: Decimal,
    ) -> Decimal:
        """
        Calculate position size based on risk.

        Args:
            capital: Available capital
            risk_per_trade: Maximum risk per trade (as decimal)
            entry_price: Entry price
            stop_loss: Stop loss price

        Returns:
            Position size in base currency
        """
        risk_amount = capital * risk_per_trade
        price_risk = abs(entry_price - stop_loss)

        if price_risk == 0:
            return Decimal("0")

        return risk_amount / price_risk

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        """Update strategy state only after a signal was actually filled."""

    def update_state(self, key: str, value: Any) -> None:
        """Update strategy state."""
        self.state[key] = value

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get strategy state."""
        return self.state.get(key, default)
