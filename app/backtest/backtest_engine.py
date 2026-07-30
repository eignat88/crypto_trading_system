from decimal import Decimal
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable
import structlog

from app.backtest.portfolio import Portfolio
from app.backtest.commission_model import CommissionModel, CommissionConfig
from app.backtest.slippage_model import SlippageModel, SlippageConfig

logger = structlog.get_logger()


@dataclass
class BacktestConfig:
    """Backtest configuration."""
    initial_balance: Decimal = Decimal("5000")
    commission_config: CommissionConfig = field(default_factory=CommissionConfig)
    slippage_config: SlippageConfig = field(default_factory=SlippageConfig)
    random_seed: int = 42


@dataclass
class BacktestResult:
    """Backtest results."""
    portfolio: Portfolio
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    sharpe_ratio: Optional[Decimal] = None
    win_rate: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    average_trade: Decimal = Decimal("0")
    average_win: Decimal = Decimal("0")
    average_loss: Decimal = Decimal("0")
    max_consecutive_losses: int = 0
    recovery_time_days: int = 0


class BacktestEngine:
    """Engine for running backtests."""

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.portfolio = Portfolio(self.config.initial_balance)
        self.commission_model = CommissionModel(self.config.commission_config)
        self.slippage_model = SlippageModel(
            self.config.slippage_config,
            seed=self.config.random_seed,
        )

    def run(
        self,
        candles: list[dict],
        strategy: Callable,
        initial_state: dict = None,
    ) -> BacktestResult:
        """
        Run backtest on historical data.

        Args:
            candles: List of candle data with keys: open_time, open, high, low, close, volume
            strategy: Strategy function that receives (candle, portfolio, state) and returns signals
            initial_state: Initial state for strategy

        Returns:
            BacktestResult with performance metrics
        """
        state = initial_state or {}
        peak_equity = self.config.initial_balance

        logger.info(
            "backtest_started",
            candles=len(candles),
            initial_balance=self.config.initial_balance,
        )

        for i, candle in enumerate(candles):
            timestamp = candle["open_time"]
            current_price = candle["close"]

            # Update portfolio with current prices
            self.portfolio.update_positions(
                {candle["symbol"]: current_price},
                timestamp,
            )

            # Check stop levels
            symbols_to_close = self.portfolio.check_stops(
                {candle["symbol"]: current_price}
            )
            for symbol in symbols_to_close:
                self._close_position(symbol, current_price, timestamp)

            # Get strategy signals
            signals = strategy(candle, self.portfolio, state)

            # Process signals
            if signals:
                for signal in signals:
                    self._process_signal(signal, candle, timestamp)

            # Update peak equity and drawdown
            current_equity = self.portfolio.total_equity
            if current_equity > peak_equity:
                peak_equity = current_equity

            drawdown = (peak_equity - current_equity) / peak_equity
            if drawdown > self.portfolio.max_drawdown if hasattr(self.portfolio, 'max_drawdown') else Decimal("0"):
                self.portfolio.max_drawdown = drawdown

        # Close any remaining positions at last price
        if candles:
            last_price = candles[-1]["close"]
            last_time = candles[-1]["open_time"]
            for symbol in list(self.portfolio.positions.keys()):
                self._close_position(symbol, last_price, last_time)

        # Calculate results
        result = self._calculate_results()

        logger.info(
            "backtest_completed",
            total_trades=result.total_trades,
            win_rate=result.win_rate,
            total_pnl=result.total_pnl,
            max_drawdown=result.max_drawdown,
        )

        return result

    def _process_signal(self, signal: dict, candle: dict, timestamp: datetime):
        """Process a trading signal."""
        action = signal.get("action")
        symbol = signal.get("symbol", candle.get("symbol"))
        price = signal.get("price", candle["close"])
        quantity = signal.get("quantity")

        if action == "buy" and quantity:
            self._open_position(symbol, "long", price, quantity, timestamp)
        elif action == "sell" and quantity:
            self._close_position(symbol, price, timestamp)
        elif action == "open_long" and quantity:
            self._open_position(symbol, "long", price, quantity, timestamp)
        elif action == "open_short" and quantity:
            self._open_position(symbol, "short", price, quantity, timestamp)
        elif action == "close":
            self._close_position(symbol, price, timestamp)

    def _open_position(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        timestamp: datetime,
    ):
        """Open a new position with slippage and commission."""
        # Apply slippage
        execution_price = self.slippage_model.calculate_slippage(
            price, quantity, is_buy=(side == "long")
        )

        # Calculate commission
        commission = self.commission_model.calculate_commission(
            quantity, execution_price, is_maker=False
        )

        # Check if we have enough balance
        cost = execution_price * quantity + commission
        if cost > self.portfolio.balance:
            return

        # Open position
        self.portfolio.open_position(
            symbol=symbol,
            side=side,
            price=execution_price,
            quantity=quantity,
            timestamp=timestamp,
            commission=commission,
        )

    def _close_position(self, symbol: str, price: Decimal, timestamp: datetime):
        """Close an existing position with slippage and commission."""
        if not self.portfolio.has_position(symbol):
            return

        position = self.portfolio.get_position(symbol)

        # Apply slippage
        execution_price = self.slippage_model.calculate_slippage(
            price, position.quantity, is_buy=(position.side == "short")
        )

        # Calculate commission
        commission = self.commission_model.calculate_commission(
            position.quantity, execution_price, is_maker=False
        )

        # Close position
        self.portfolio.close_position(
            symbol=symbol,
            price=execution_price,
            timestamp=timestamp,
            commission=commission,
        )

    def _calculate_results(self) -> BacktestResult:
        """Calculate backtest performance metrics."""
        trades = self.portfolio.trade_history
        close_trades = [t for t in trades if t["type"] == "close"]

        result = BacktestResult(portfolio=self.portfolio)
        result.total_trades = len(close_trades)

        if not close_trades:
            return result

        # Calculate PnL metrics
        pnls = [t["pnl"] for t in close_trades]
        result.total_pnl = sum(pnls)

        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        result.winning_trades = len(wins)
        result.losing_trades = len(losses)

        if result.total_trades > 0:
            result.win_rate = Decimal(str(len(wins))) / Decimal(str(result.total_trades))

        if wins:
            result.average_win = sum(wins) / Decimal(str(len(wins)))

        if losses:
            result.average_loss = sum(losses) / Decimal(str(len(losses)))

        result.average_trade = result.total_pnl / Decimal(str(result.total_trades))

        # Profit factor
        if losses and sum(abs(l) for l in losses) > 0:
            result.profit_factor = sum(wins) / sum(abs(l) for l in losses)

        # Max consecutive losses
        consecutive_losses = 0
        max_consecutive = 0
        for pnl in pnls:
            if pnl <= 0:
                consecutive_losses += 1
                max_consecutive = max(max_consecutive, consecutive_losses)
            else:
                consecutive_losses = 0
        result.max_consecutive_losses = max_consecutive

        # Max drawdown
        if hasattr(self.portfolio, 'max_drawdown'):
            result.max_drawdown = self.portfolio.max_drawdown

        return result
