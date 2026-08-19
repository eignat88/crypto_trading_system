"""PnL and performance metrics for paper trading."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from collections.abc import Sequence
from typing import Protocol

from app.exchange.paper_execution_engine import PaperExecutionEngine
from app.models.candle import Candle
from app.models.paper_fill_state import PaperFillState
from app.models.paper_order_state import PaperOrderState
from app.models.paper_position_state import PaperPositionState
from app.models.paper_pnl_snapshot_state import PaperPnLSnapshotState


logger = logging.getLogger(__name__)


@dataclass
class PnLRecord:
    """Single PnL measurement at a point in time."""

    timestamp: datetime
    equity: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    total_pnl: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    cash_balance: Decimal = Decimal("0")
    position_value: Decimal = Decimal("0")


@dataclass
class EquityPoint:
    """Point on the equity curve."""

    timestamp: datetime
    sequence: int
    equity: Decimal
    drawdown: Decimal = Decimal("0")
    drawdown_pct: Decimal = Decimal("0")


@dataclass
class TradingMetrics:
    """Aggregated trading metrics."""

    total_realized_pnl: Decimal = Decimal("0")
    total_unrealized_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")
    total_slippage: Decimal = Decimal("0")
    win_count: int = 0
    loss_count: int = 0
    total_trades: int = 0
    win_rate: Decimal = Decimal("0")
    avg_win: Decimal = Decimal("0")
    avg_loss: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    max_drawdown_pct: Decimal = Decimal("0")


class MarketPriceProvider(Protocol):
    """Protocol for getting current market prices."""

    def get_price(self, symbol: str) -> Decimal | None:
        """Get current price for symbol."""
        ...


class EnginePriceProvider:
    """Get prices from PaperExecutionEngine."""

    def __init__(self, engine: PaperExecutionEngine) -> None:
        self.engine = engine

    def get_price(self, symbol: str) -> Decimal | None:
        if self.engine.last_candle is None:
            return None
        if self.engine.last_candle.symbol != symbol:
            # Could search positions or return None
            pass
        return self.engine.last_candle.close


class PaperPnLTracker:
    """Track PnL, fees, slippage and equity curve for paper trading.

    Responsibilities:
    - Calculate realized PnL from closed positions
    - Calculate unrealized PnL from open positions
    - Track fees and slippage
    - Build equity curve with drawdown
    - Provide aggregated metrics
    """

    def __init__(
        self,
        initial_capital: Decimal = Decimal("10000"),
        fee_rate: Decimal = Decimal("0.001"),  # 0.1% default
    ) -> None:
        self.initial_capital = initial_capital
        self.fee_rate = fee_rate

        self._pnl_records: list[PnLRecord] = []
        self._equity_curve: list[EquityPoint] = []
        self._trade_pnl: list[Decimal] = []  # Individual trade PnL
        self._fees_paid: Decimal = Decimal("0")
        self._slippage_total: Decimal = Decimal("0")
        self._peak_equity: Decimal = initial_capital
        self._entry_prices: dict[str, Decimal] = {}  # Track entry prices per symbol

    @property
    def pnl_records(self) -> list[PnLRecord]:
        return self._pnl_records.copy()

    @property
    def equity_curve(self) -> list[EquityPoint]:
        return self._equity_curve.copy()

    @property
    def current_equity(self) -> Decimal:
        """Calculate current equity."""
        if not self._pnl_records:
            return self.initial_capital
        return self._pnl_records[-1].equity

    @property
    def current_drawdown(self) -> Decimal:
        """Calculate current drawdown from peak."""
        if not self._pnl_records:
            return Decimal("0")
        current = self.current_equity
        return max(Decimal("0"), self._peak_equity - current)

    @property
    def current_drawdown_pct(self) -> Decimal:
        """Calculate current drawdown percentage from peak."""
        if self._peak_equity == 0:
            return Decimal("0")
        return (self.current_drawdown / self._peak_equity) * Decimal("100")

    def calculate_realized_pnl(
        self,
        fills: list[PaperFillState],
        orders: list[PaperOrderState],
        positions: dict[str, PaperPositionState],
    ) -> Decimal:
        """Calculate realized PnL from executed fills.

        For spot trading, realized PnL occurs when:
        - Selling a position that was bought earlier
        - The difference between sell price and average buy price

        Args:
            fills: List of all fills
            orders: Orders corresponding to the fills; their side determines direction
            positions: Current positions

        Returns:
            Total realized PnL
        """
        del positions  # The fill history is the source of truth for realized PnL.

        orders_by_id = {order.order_id: order for order in orders}

        # Track cumulative position per symbol
        position_tracker: dict[str, dict[str, Decimal]] = {}
        realized_pnl = Decimal("0")
        trade_pnl_records: list[Decimal] = []

        for fill in fills:
            symbol = fill.symbol
            qty = fill.quantity
            price = fill.price
            order = orders_by_id.get(fill.order_id)
            if order is None:
                raise ValueError(f"Order not found for fill {fill.fill_id}")

            side = order.side.upper()
            if side not in {"BUY", "SELL"}:
                raise ValueError(f"Unsupported order side: {order.side}")

            if symbol not in position_tracker:
                position_tracker[symbol] = {
                    "quantity": Decimal("0"),
                    "avg_cost": Decimal("0"),
                    "cost_basis": Decimal("0"),
                }

            tracker = position_tracker[symbol]

            current_qty = tracker["quantity"]

            if side == "BUY":
                new_qty = current_qty + qty
                # Update average cost
                old_cost_basis = tracker["cost_basis"]
                new_cost_basis = old_cost_basis + (qty * price)
                tracker["quantity"] = new_qty
                tracker["cost_basis"] = new_cost_basis
                if new_qty > 0:
                    tracker["avg_cost"] = new_cost_basis / new_qty
            else:
                sell_qty = qty
                if sell_qty > current_qty:
                    raise ValueError(
                        f"Sell quantity {sell_qty} exceeds tracked position "
                        f"{current_qty} for {symbol}"
                    )
                new_qty = current_qty - sell_qty
                # Realize PnL on sold portion
                avg_cost = tracker["avg_cost"]
                sale_proceeds = sell_qty * price
                cost_of_sold = sell_qty * avg_cost
                trade_pnl = sale_proceeds - cost_of_sold

                realized_pnl += trade_pnl
                trade_pnl_records.append(trade_pnl)

                # Update tracker
                tracker["quantity"] = new_qty
                tracker["cost_basis"] = new_qty * avg_cost if new_qty > 0 else Decimal("0")

        # Replace metrics derived from this complete fill history so recalculation is idempotent.
        self._trade_pnl = trade_pnl_records
        return realized_pnl

    def calculate_unrealized_pnl(
        self,
        positions: dict[str, PaperPositionState],
        price_provider: MarketPriceProvider,
    ) -> Decimal:
        """Calculate unrealized PnL from open positions.

        Args:
            positions: Current positions
            price_provider: Provider for current market prices

        Returns:
            Total unrealized PnL
        """
        unrealized_pnl = Decimal("0")

        for symbol, position in positions.items():
            if position.quantity == 0:
                continue

            current_price = price_provider.get_price(symbol)
            if current_price is None:
                continue

            # Unrealized PnL = (current_price - avg_entry) * quantity
            entry_price = position.average_price
            price_diff = current_price - entry_price
            position_unrealized = price_diff * position.quantity

            unrealized_pnl += position_unrealized

        return unrealized_pnl

    def calculate_fees(self, fills: list[PaperFillState]) -> Decimal:
        """Calculate total fees paid.

        Args:
            fills: List of all fills

        Returns:
            Total fees
        """
        total_fees = Decimal("0")

        for fill in fills:
            # Fee = quantity * price * fee_rate
            trade_value = fill.quantity * fill.price
            fee = abs(trade_value) * self.fee_rate
            total_fees += fee

        self._fees_paid = total_fees
        return total_fees

    def calculate_slippage(
        self,
        fills: list[PaperFillState],
        expected_prices: dict[str, Decimal],
    ) -> Decimal:
        """Calculate total slippage.

        Slippage = |execution_price - expected_price| * quantity

        Args:
            fills: Executed fills
            expected_prices: Expected prices at order time

        Returns:
            Total slippage
        """
        total_slippage = Decimal("0")

        for fill in fills:
            expected = expected_prices.get(fill.fill_id, fill.price)
            slippage_per_unit = abs(fill.price - expected)
            slippage = slippage_per_unit * fill.quantity
            total_slippage += slippage

        self._slippage_total = total_slippage
        return total_slippage

    def record_snapshot(
        self,
        timestamp: datetime | None = None,
        sequence: int = 0,
        engine: PaperExecutionEngine | None = None,
        realized_pnl: Decimal | None = None,
        unrealized_pnl: Decimal | None = None,
    ) -> PnLRecord:
        """Record a snapshot of current PnL state.

        Args:
            timestamp: Time of snapshot (defaults to now)
            sequence: Market event sequence number
            engine: Execution engine for current state
            realized_pnl: Pre-calculated realized PnL
            unrealized_pnl: Pre-calculated unrealized PnL

        Returns:
            PnLRecord with current metrics
        """
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)

        # Normalize PnL values
        realized_pnl_val = realized_pnl if realized_pnl is not None else Decimal("0")
        unrealized_pnl_val = unrealized_pnl if unrealized_pnl is not None else Decimal("0")
        total_pnl = realized_pnl_val + unrealized_pnl_val

        if engine is not None:
            # Use engine state for cash and position values
            price_provider = EnginePriceProvider(engine)

            if unrealized_pnl is None:
                unrealized_pnl_val = self.calculate_unrealized_pnl(
                    engine.positions,
                    price_provider,
                )
                total_pnl = realized_pnl_val + unrealized_pnl_val

            cash_balance = engine.cash_balance
            position_values = []

            for symbol, position in engine.positions.items():
                if position.quantity > 0:
                    price = price_provider.get_price(symbol)
                    if price:
                        position_values.append(position.quantity * price)

            position_value = sum(position_values, Decimal("0"))
            equity = cash_balance + position_value
        else:
            # No engine: calculate equity from initial capital + PnL
            cash_balance = self.initial_capital
            position_value = Decimal("0")
            equity = self.initial_capital + total_pnl

        # Update peak equity for drawdown calculation
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = max(Decimal("0"), self._peak_equity - equity)
        drawdown_pct = (drawdown / self._peak_equity * Decimal("100")) if self._peak_equity > 0 else Decimal("0")

        record = PnLRecord(
            timestamp=timestamp,
            equity=equity,
            realized_pnl=realized_pnl_val,
            unrealized_pnl=unrealized_pnl_val,
            total_pnl=total_pnl,
            fees_paid=self._fees_paid,
            slippage=self._slippage_total,
            cash_balance=cash_balance,
            position_value=position_value,
        )

        self._pnl_records.append(record)

        # Add to equity curve
        self._equity_curve.append(EquityPoint(
            timestamp=timestamp,
            sequence=sequence,
            equity=equity,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
        ))

        return record

    def snapshot_state(self, record: PnLRecord | None = None) -> PaperPnLSnapshotState:
        """Convert a successfully recorded snapshot to its persistence model."""
        if not self._pnl_records or not self._equity_curve:
            raise ValueError("No PnL snapshot has been recorded")
        record = record or self._pnl_records[-1]
        try:
            index = next(i for i in range(len(self._pnl_records) - 1, -1, -1)
                         if self._pnl_records[i] is record)
        except StopIteration as exc:
            raise ValueError("Record does not belong to this tracker") from exc
        point = self._equity_curve[index]
        return PaperPnLSnapshotState(
            snapshot_time=record.timestamp, sequence=point.sequence,
            equity=record.equity, realized_pnl=record.realized_pnl,
            unrealized_pnl=record.unrealized_pnl, total_pnl=record.total_pnl,
            fees_paid=record.fees_paid, slippage=record.slippage,
            cash_balance=record.cash_balance, position_value=record.position_value,
            drawdown=point.drawdown, drawdown_pct=point.drawdown_pct,
        )

    def restore_snapshots(self, snapshots: Sequence[PaperPnLSnapshotState]) -> None:
        """Replace reporting state with durable snapshots without duplicating data."""
        if not snapshots:
            return
        ordered = sorted(snapshots, key=lambda item: (item.snapshot_time, item.sequence))
        unique = {(item.snapshot_time, item.sequence): item for item in ordered}
        ordered = sorted(unique.values(), key=lambda item: (item.snapshot_time, item.sequence))
        self._pnl_records = [
            PnLRecord(
                timestamp=item.snapshot_time, equity=item.equity,
                realized_pnl=item.realized_pnl, unrealized_pnl=item.unrealized_pnl,
                total_pnl=item.total_pnl, fees_paid=item.fees_paid,
                slippage=item.slippage, cash_balance=item.cash_balance,
                position_value=item.position_value,
            ) for item in ordered
        ]
        self._equity_curve = [
            EquityPoint(
                timestamp=item.snapshot_time, sequence=item.sequence,
                equity=item.equity, drawdown=item.drawdown,
                drawdown_pct=item.drawdown_pct,
            ) for item in ordered
        ]
        self._fees_paid = ordered[-1].fees_paid
        self._slippage_total = ordered[-1].slippage
        self._peak_equity = max(point.equity + point.drawdown for point in self._equity_curve)

    def calculate_metrics(self) -> TradingMetrics:
        """Calculate aggregated trading metrics.

        Returns:
            TradingMetrics with summary statistics
        """
        metrics = TradingMetrics()

        # Always include fees and slippage
        metrics.total_fees = self._fees_paid
        metrics.total_slippage = self._slippage_total

        if not self._trade_pnl:
            return metrics

        # Win/loss analysis
        wins = [p for p in self._trade_pnl if p > 0]
        losses = [p for p in self._trade_pnl if p < 0]

        metrics.win_count = len(wins)
        metrics.loss_count = len(losses)
        metrics.total_trades = len(self._trade_pnl)

        if wins:
            metrics.avg_win = sum(wins) / len(wins)
        if losses:
            metrics.avg_loss = abs(sum(losses) / len(losses))

        metrics.total_realized_pnl = sum(self._trade_pnl, Decimal("0"))

        if metrics.total_trades > 0:
            metrics.win_rate = Decimal(metrics.win_count) / Decimal(metrics.total_trades)

        # Profit factor = gross profit / gross loss
        gross_profit = sum(wins, Decimal("0"))
        gross_loss = abs(sum(losses, Decimal("0")))
        if gross_loss > 0:
            metrics.profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            metrics.profit_factor = Decimal("999")  # Infinite practically

        # Drawdown from equity curve
        if self._equity_curve:
            max_dd = max(p.drawdown for p in self._equity_curve)
            max_dd_pct = max(p.drawdown_pct for p in self._equity_curve)
            metrics.max_drawdown = max_dd
            metrics.max_drawdown_pct = max_dd_pct

        return metrics

    def reset(self) -> None:
        """Reset all tracking data."""
        self._pnl_records.clear()
        self._equity_curve.clear()
        self._trade_pnl.clear()
        self._fees_paid = Decimal("0")
        self._slippage_total = Decimal("0")
        self._peak_equity = self.initial_capital
        self._entry_prices.clear()
