from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.models import Position


@dataclass(frozen=True)
class ExitLevelEvent:
    """Deterministic intrabar exit detected from candle OHLC."""

    symbol: str
    reference_price: Decimal
    reason: str


class Portfolio:
    """Manages virtual portfolio for backtesting."""

    def __init__(self, initial_balance: Decimal = Decimal("5000")):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []
        self.trade_history: list[dict[str, Any]] = []
        self.equity_history: list[tuple[datetime, Decimal]] = []
        self.max_drawdown = Decimal("0")

    @property
    def total_equity(self) -> Decimal:
        """Calculate total portfolio equity."""
        positions_value = sum(
            (pos.position_value for pos in self.positions.values()),
            Decimal("0"),
        )
        return self.balance + positions_value

    @property
    def unrealized_pnl(self) -> Decimal:
        """Calculate total unrealized PnL."""
        return sum(
            (pos.unrealized_pnl for pos in self.positions.values()),
            Decimal("0"),
        )

    @property
    def realized_pnl(self) -> Decimal:
        """Calculate total realized PnL."""
        return sum(
            (Decimal(str(trade.get("pnl", "0"))) for trade in self.trade_history),
            Decimal("0"),
        )

    def open_position(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        timestamp: datetime,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
        commission: Decimal = Decimal("0"),
    ) -> bool:
        """
        Open a new position.

        Returns:
            True if position opened successfully
        """
        if side != "long" or quantity <= 0:
            return False

        cost = price * quantity + commission

        if cost > self.balance:
            return False

        self.balance -= cost

        position = self.positions.get(symbol)
        if position is None:
            position = Position(
                symbol=symbol,
                side=side,
                entry_price=price,
                quantity=quantity,
                entry_time=timestamp,
                stop_loss=stop_loss,
                take_profit=take_profit,
                current_price=price,
                entry_commission=commission,
                high_water_mark=price,
            )
            self.positions[symbol] = position
        else:
            # A repeated spot buy is a DCA fill, not a replacement position.
            total_quantity = position.quantity + quantity
            position.entry_price = (
                position.entry_price * position.quantity + price * quantity
            ) / total_quantity
            position.quantity = total_quantity
            position.entry_commission += commission
            position.current_price = price
            position.stop_loss = stop_loss if stop_loss is not None else position.stop_loss
            position.take_profit = take_profit if take_profit is not None else position.take_profit
            position.update_market(price, price)

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
    ) -> Decimal | None:
        """
        Close an existing position.

        Returns:
            Realized PnL or None if no position exists
        """
        if symbol not in self.positions:
            return None

        position = self.positions.pop(symbol)

        pnl = (
            (price - position.entry_price) * position.quantity
            - position.entry_commission
            - commission
        )

        # Update balance
        proceeds = price * position.quantity - commission
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

    def update_positions(
        self,
        prices: dict[str, Decimal],
        timestamp: datetime,
        highs: dict[str, Decimal] | None = None,
    ) -> None:
        """Update unrealized PnL for all positions."""
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.update_market(
                    prices[symbol],
                    (highs or {}).get(symbol),
                )

        # Record equity
        self.equity_history.append((timestamp, self.total_equity))

    def check_intrabar_exits(
        self,
        candles: dict[str, dict[str, Decimal]],
    ) -> list[ExitLevelEvent]:
        """Detect stop-loss/take-profit from candle OHLC without future data.

        Conservative rules for long spot positions:
        - ``low <= stop_loss`` triggers the stop.
        - ``high >= take_profit`` triggers the take-profit.
        - if both levels are touched in the same candle, stop-loss wins because
          OHLC does not reveal the intrabar path.
        - if the candle opens below the stop, the open price is used as the
          reference price (adverse gap); otherwise the stop level is used.
        - take-profit uses the configured level as the reference price even on
          a favorable gap, avoiding optimistic price improvement.

        Slippage is applied later by the execution model.
        """
        events: list[ExitLevelEvent] = []

        for symbol, position in self.positions.items():
            candle = candles.get(symbol)
            if candle is None or position.side != "long":
                continue

            open_price = candle["open"]
            high_price = candle["high"]
            low_price = candle["low"]

            if position.stop_loss is not None and low_price <= position.stop_loss:
                gap_down = open_price <= position.stop_loss
                reference_price = open_price if gap_down else position.stop_loss
                events.append(
                    ExitLevelEvent(
                        symbol=symbol,
                        reference_price=reference_price,
                        reason="Stop-loss hit on gap" if gap_down else "Stop-loss hit",
                    )
                )
                # Conservative ambiguity rule: stop wins if both levels were
                # touched in this candle.
                continue

            if position.take_profit is not None and high_price >= position.take_profit:
                events.append(
                    ExitLevelEvent(
                        symbol=symbol,
                        reference_price=position.take_profit,
                        reason="Take-profit hit",
                    )
                )

        return events

    def check_stops(self, prices: dict[str, Decimal]) -> list[str]:
        """Legacy close-price stop/take check kept for compatibility."""
        symbols_to_close = []

        for symbol, position in self.positions.items():
            if symbol not in prices:
                continue

            current_price = prices[symbol]

            if position.stop_loss is not None:
                if position.side == "long" and current_price <= position.stop_loss:
                    symbols_to_close.append(symbol)

            if position.take_profit is not None:
                if position.side == "long" and current_price >= position.take_profit:
                    symbols_to_close.append(symbol)

        return symbols_to_close

    def get_position(self, symbol: str) -> Position | None:
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
