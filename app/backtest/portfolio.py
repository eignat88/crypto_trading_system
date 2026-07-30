from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    """Represents a trading position."""
    symbol: str
    side: str  # 'long' or 'short'
    entry_price: Decimal
    quantity: Decimal
    entry_time: datetime
    stop_loss: Optional[Decimal] = None
    take_profit: Optional[Decimal] = None
    trailing_stop: Optional[Decimal] = None
    unrealized_pnl: Decimal = Decimal("0")

    @property
    def position_value(self) -> Decimal:
        return self.entry_price * self.quantity

    def update_pnl(self, current_price: Decimal):
        if self.side == "long":
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity


class Portfolio:
    """Manages virtual portfolio for backtesting."""

    def __init__(self, initial_balance: Decimal = Decimal("5000")):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []
        self.trade_history: list[dict] = []
        self.equity_history: list[tuple[datetime, Decimal]] = []

    @property
    def total_equity(self) -> Decimal:
        """Calculate total portfolio equity."""
        positions_value = sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )
        return self.balance + positions_value

    @property
    def unrealized_pnl(self) -> Decimal:
        """Calculate total unrealized PnL."""
        return sum(pos.unrealized_pnl for pos in self.positions.values())

    @property
    def realized_pnl(self) -> Decimal:
        """Calculate total realized PnL."""
        return sum(
            trade.get("pnl", Decimal("0")) for trade in self.trade_history
        )

    def open_position(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        timestamp: datetime,
        stop_loss: Optional[Decimal] = None,
        take_profit: Optional[Decimal] = None,
        commission: Decimal = Decimal("0"),
    ) -> bool:
        """
        Open a new position.

        Returns:
            True if position opened successfully
        """
        cost = price * quantity + commission

        if cost > self.balance:
            return False

        self.balance -= cost

        position = Position(
            symbol=symbol,
            side=side,
            entry_price=price,
            quantity=quantity,
            entry_time=timestamp,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        self.positions[symbol] = position

        self.trade_history.append({
            "type": "open",
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": quantity,
            "timestamp": timestamp,
            "commission": commission,
        })

        return True

    def close_position(
        self,
        symbol: str,
        price: Decimal,
        timestamp: datetime,
        commission: Decimal = Decimal("0"),
    ) -> Optional[Decimal]:
        """
        Close an existing position.

        Returns:
            Realized PnL or None if no position exists
        """
        if symbol not in self.positions:
            return None

        position = self.positions.pop(symbol)

        # Calculate PnL
        if position.side == "long":
            pnl = (price - position.entry_price) * position.quantity
        else:
            pnl = (position.entry_price - price) * position.quantity

        pnl -= commission

        # Update balance
        proceeds = position.entry_price * position.quantity + pnl
        self.balance += proceeds

        # Record trade
        self.trade_history.append({
            "type": "close",
            "symbol": symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "exit_price": price,
            "quantity": position.quantity,
            "pnl": pnl,
            "commission": commission,
            "entry_time": position.entry_time,
            "exit_time": timestamp,
            "duration": timestamp - position.entry_time,
        })

        # Archive position
        position.unrealized_pnl = pnl
        self.closed_positions.append(position)

        return pnl

    def update_positions(self, prices: dict[str, Decimal], timestamp: datetime):
        """Update unrealized PnL for all positions."""
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.update_pnl(prices[symbol])

        # Record equity
        self.equity_history.append((timestamp, self.total_equity))

    def check_stops(self, prices: dict[str, Decimal]) -> list[str]:
        """
        Check stop-loss and take-profit levels.

        Returns:
            List of symbols that should be closed
        """
        symbols_to_close = []

        for symbol, position in self.positions.items():
            if symbol not in prices:
                continue

            current_price = prices[symbol]

            # Check stop-loss
            if position.stop_loss is not None:
                if position.side == "long" and current_price <= position.stop_loss:
                    symbols_to_close.append(symbol)
                elif position.side == "short" and current_price >= position.stop_loss:
                    symbols_to_close.append(symbol)

            # Check take-profit
            if position.take_profit is not None:
                if position.side == "long" and current_price >= position.take_profit:
                    symbols_to_close.append(symbol)
                elif position.side == "short" and current_price <= position.take_profit:
                    symbols_to_close.append(symbol)

        return symbols_to_close

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a symbol."""
        return self.positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        """Check if position exists for a symbol."""
        return symbol in self.positions

    def get_position_value(self, symbol: str, current_price: Decimal) -> Decimal:
        """Get current value of a position."""
        if symbol not in self.positions:
            return Decimal("0")

        position = self.positions[symbol]
        return current_price * position.quantity
