from collections.abc import Callable
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from decimal import Decimal

import structlog

from app.backtest.commission_model import CommissionConfig, CommissionModel
from app.backtest.portfolio import Portfolio
from app.backtest.slippage_model import SlippageConfig, SlippageModel
from app.risk.risk_engine import RiskEngine, RiskEvent

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
    sharpe_ratio: Decimal | None = None
    win_rate: Decimal = Decimal("0")
    profit_factor: Decimal = Decimal("0")
    average_trade: Decimal = Decimal("0")
    average_win: Decimal = Decimal("0")
    average_loss: Decimal = Decimal("0")
    max_consecutive_losses: int = 0
    recovery_time_days: int = 0


class BacktestEngine:
    """Engine for running backtests."""

    def __init__(self, config: BacktestConfig = None, risk_engine: RiskEngine = None):
        self.config = config or BacktestConfig()
        self.portfolio = Portfolio(self.config.initial_balance)
        self.commission_model = CommissionModel(self.config.commission_config)
        self.slippage_model = SlippageModel(
            self.config.slippage_config,
            seed=self.config.random_seed,
        )
        self.risk_engine = risk_engine or RiskEngine()

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
            self.risk_engine.update_equity(self.portfolio.total_equity)

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
                if isinstance(signals, dict) or is_dataclass(signals):
                    signals = [signals]
                for signal in signals:
                    self._process_signal(signal, candle, timestamp)

            # Update peak equity and drawdown
            current_equity = self.portfolio.total_equity
            if current_equity > peak_equity:
                peak_equity = current_equity

            drawdown = (peak_equity - current_equity) / peak_equity
            if drawdown > self.portfolio.max_drawdown:
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
        if is_dataclass(signal) and not isinstance(signal, type):
            signal = asdict(signal)
        if not isinstance(signal, dict):
            raise TypeError("Strategy signals must be dictionaries or dataclass instances")

        action = signal.get("action")
        symbol = signal.get("symbol", candle.get("symbol"))
        price = signal.get("price", candle["close"])
        quantity = signal.get("quantity")
        stop_loss = signal.get("stop_loss")
        take_profit = signal.get("take_profit")

        if action == "buy" and quantity:
            self._open_position(symbol, "long", price, quantity, timestamp, stop_loss, take_profit)
        elif action == "sell" and quantity:
            self._close_position(symbol, price, timestamp)
        elif action == "open_long" and quantity:
            self._open_position(symbol, "long", price, quantity, timestamp, stop_loss, take_profit)
        elif action == "close":
            self._close_position(symbol, price, timestamp)

    def _open_position(
        self,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        timestamp: datetime,
        stop_loss: Decimal | None = None,
        take_profit: Decimal | None = None,
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

        current_positions = {
            key: {
                "symbol": position.symbol,
                "value": position.position_value,
            }
            for key, position in self.portfolio.positions.items()
        }
        risk_result = self.risk_engine.check_trade(
            symbol=symbol,
            side="buy",
            quantity=quantity,
            price=execution_price,
            current_balance=self.portfolio.balance,
            current_positions=current_positions,
            total_capital=self.portfolio.total_equity,
            stop_loss_price=stop_loss,
        )
        if not risk_result.approved:
            only_position_size_exceeded = (
                risk_result.events == [RiskEvent.MAX_POSITION_SIZE]
                and len(risk_result.reasons) == 2
                and risk_result.adjusted_quantity is not None
            )
            if not only_position_size_exceeded:
                return
            quantity = risk_result.adjusted_quantity
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
            stop_loss=stop_loss,
            take_profit=take_profit,
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
        if losses and sum(abs(loss) for loss in losses) > 0:
            result.profit_factor = sum(wins) / sum(abs(loss) for loss in losses)

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
        result.max_drawdown = self.portfolio.max_drawdown

        return result
