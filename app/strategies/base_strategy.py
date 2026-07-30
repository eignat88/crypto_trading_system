from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional


@dataclass
class Signal:
    """Trading signal."""
    action: str  # 'buy', 'sell', 'open_long', 'open_short', 'close'
    symbol: str
    price: Decimal
    quantity: Decimal
    timestamp: datetime
    reason: str = ""
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None


class BaseStrategy(ABC):
    """Base class for trading strategies."""

    def __init__(self, name: str, symbols: list[str]):
        self.name = name
        self.symbols = symbols
        self.state = {}

    @abstractmethod
    def should_enter(
        self,
        candle: dict,
        indicators: dict,
        portfolio_state: dict,
    ) -> Optional[Signal]:
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
        candle: dict,
        indicators: dict,
        position: dict,
    ) -> Optional[Signal]:
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

    def update_state(self, key: str, value):
        """Update strategy state."""
        self.state[key] = value

    def get_state(self, key: str, default=None):
        """Get strategy state."""
        return self.state.get(key, default)
