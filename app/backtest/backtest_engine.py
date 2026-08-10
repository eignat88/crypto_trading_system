"""Spot-only backtest orchestration with auditable risk decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog

from app.backtest.commission_model import CommissionConfig, CommissionModel
from app.backtest.portfolio import Portfolio
from app.backtest.slippage_model import SlippageConfig, SlippageModel
from app.models import Fill, Order, RiskDecision, Signal, SignalAction
from app.risk.risk_engine import RiskCheckResult, RiskEngine
from app.strategies.base_strategy import BaseStrategy

logger = structlog.get_logger()

LegacyStrategy = Callable[[dict[str, Any], Portfolio, dict[str, Any]], Any]
IndicatorProvider = Callable[[dict[str, Any], int], dict[str, Any]]


@dataclass
class BacktestConfig:
    """Backtest configuration."""

    initial_balance: Decimal = Decimal("5000")
    commission_config: CommissionConfig = field(default_factory=CommissionConfig)
    slippage_config: SlippageConfig = field(default_factory=SlippageConfig)
    random_seed: int = 42


@dataclass
class BacktestResult:
    """Backtest results plus a complete decision and execution audit trail."""

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
    signals: list[Signal] = field(default_factory=list)
    risk_decisions: list[RiskDecision] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)


class BacktestEngine:
    """Run Candle → Strategy → Risk → Order → Fill → Portfolio."""

    def __init__(
        self,
        config: BacktestConfig | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.config = config or BacktestConfig()
        self.portfolio = Portfolio(self.config.initial_balance)
        self.commission_model = CommissionModel(self.config.commission_config)
        self.slippage_model = SlippageModel(
            self.config.slippage_config,
            seed=self.config.random_seed,
        )
        self.risk_engine = risk_engine or RiskEngine()
        self.signals: list[Signal] = []
        self.risk_decisions: list[RiskDecision] = []
        self.orders: list[Order] = []
        self.fills: list[Fill] = []
        self._sequence = 0

    def run(
        self,
        candles: list[dict[str, Any]],
        strategy: LegacyStrategy | BaseStrategy,
        initial_state: dict[str, Any] | None = None,
        indicator_provider: IndicatorProvider | None = None,
    ) -> BacktestResult:
        """Run a reproducible backtest.

        A ``BaseStrategy`` receives indicators either from ``indicator_provider``
        or from each candle's ``indicators`` mapping. Legacy callable strategies
        remain supported for compatibility.
        """
        state = initial_state or {}
        peak_equity = self.config.initial_balance

        logger.info(
            "backtest_started",
            candles=len(candles),
            initial_balance=self.config.initial_balance,
        )

        for index, candle in enumerate(candles):
            timestamp = self._datetime(candle["open_time"], "open_time")
            symbol = str(candle["symbol"])
            current_price = self._decimal(candle["close"], "close")
            open_price = self._decimal(candle.get("open", current_price), "open")
            high_price = self._decimal(candle.get("high", current_price), "high")
            low_price = self._decimal(candle.get("low", current_price), "low")

            closed_by_level = False
            level_events = self.portfolio.check_intrabar_exits(
                {
                    symbol: {
                        "open": open_price,
                        "high": high_price,
                        "low": low_price,
                    }
                }
            )
            for event in level_events:
                position = self.portfolio.get_position(event.symbol)
                if position is None:
                    continue
                level_signal = Signal(
                    action=SignalAction.CLOSE,
                    symbol=event.symbol,
                    price=event.reference_price,
                    quantity=position.quantity,
                    timestamp=timestamp,
                    reason=event.reason,
                    strategy="backtest_engine",
                    parameters_version="backtest_engine_v1",
                    metadata={"exit_source": "intrabar_level"},
                )
                closed_by_level = (
                    self._process_signal(level_signal, candle, timestamp) is not None
                ) or closed_by_level

            self.portfolio.update_positions(
                {symbol: current_price},
                timestamp,
                highs={symbol: high_price},
            )
            self.risk_engine.update_equity(self.portfolio.total_equity)

            indicators = (
                indicator_provider(candle, index)
                if indicator_provider is not None
                else self._indicators_from_candle(candle)
            )
            signals = (
                None
                if closed_by_level
                else self._strategy_signals(strategy, candle, indicators, state)
            )
            for signal in self._as_signal_list(signals, candle, timestamp):
                fill = self._process_signal(signal, candle, timestamp)
                if (
                    fill is not None
                    and isinstance(strategy, BaseStrategy)
                    and isinstance(signal, Signal)
                ):
                    strategy.on_fill(signal, fill)

            current_equity = self.portfolio.total_equity
            peak_equity = max(peak_equity, current_equity)
            drawdown = (peak_equity - current_equity) / peak_equity
            self.portfolio.max_drawdown = max(self.portfolio.max_drawdown, drawdown)

        if candles:
            last_candle = candles[-1]
            last_price = self._decimal(last_candle["close"], "close")
            last_time = self._datetime(last_candle["open_time"], "open_time")
            for symbol, position in list(self.portfolio.positions.items()):
                close_signal = Signal(
                    action=SignalAction.CLOSE,
                    symbol=symbol,
                    price=last_price,
                    quantity=position.quantity,
                    timestamp=last_time,
                    reason="End of backtest",
                    strategy="backtest_engine",
                    parameters_version="backtest_engine_v1",
                    metadata={"exit_source": "end_of_backtest"},
                )
                self._process_signal(close_signal, last_candle, last_time)

        result = self._calculate_results()
        logger.info(
            "backtest_completed",
            total_trades=result.total_trades,
            win_rate=result.win_rate,
            total_pnl=result.total_pnl,
            max_drawdown=result.max_drawdown,
        )
        return result

    def _strategy_signals(
        self,
        strategy: LegacyStrategy | BaseStrategy,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        state: dict[str, Any],
    ) -> Any:
        if not isinstance(strategy, BaseStrategy):
            return strategy(candle, self.portfolio, state)

        symbol = str(candle["symbol"])
        position = self.portfolio.get_position(symbol)
        if position is None:
            return strategy.should_enter(
                candle,
                indicators,
                {
                    "has_position": False,
                    "capital": self.portfolio.total_equity,
                    "available_balance": self.portfolio.balance,
                },
            )

        unrealized_pnl_pct = (
            (position.current_price - position.entry_price) / position.entry_price
            if position.current_price is not None
            else Decimal("0")
        )
        position_state: dict[str, Any] = {
            "symbol": position.symbol,
            "side": position.side,
            "entry_price": position.entry_price,
            "quantity": position.quantity,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "holding_periods": position.holding_periods,
            "capital": self.portfolio.total_equity,
            "high_water_mark": position.high_water_mark,
        }
        exit_signal = strategy.should_exit(candle, indicators, position_state)
        if exit_signal is not None:
            return exit_signal
        should_add_dca = getattr(strategy, "should_add_dca", None)
        return should_add_dca(candle, indicators, position_state) if should_add_dca else None

    def _process_signal(
        self,
        signal: Signal | dict[str, Any],
        candle: dict[str, Any],
        timestamp: datetime,
    ) -> Fill | None:
        normalized = self._normalize_signal(signal, candle, timestamp)
        self.signals.append(normalized)

        action = SignalAction(str(normalized.action))
        side = "buy" if action in {SignalAction.BUY, SignalAction.OPEN_LONG} else "sell"
        quantity = normalized.quantity
        if side == "sell":
            position = self.portfolio.get_position(normalized.symbol)
            if position is None:
                self.risk_decisions.append(
                    RiskDecision(
                        order_id="",
                        approved=False,
                        risk_level="HIGH",
                        codes=("NO_POSITION",),
                        reasons=("No open spot position to close",),
                        requested_quantity=quantity,
                    )
                )
                return None
            quantity = position.quantity

        order = Order(
            order_id=self._next_id("order"),
            signal=normalized,
            side=side,
            quantity=quantity,
            requested_price=normalized.price,
            created_at=timestamp,
        )
        self.orders.append(order)
        return self._execute_order(order)

    def _execute_order(self, order: Order) -> Fill | None:
        execution_price = self.slippage_model.calculate_slippage(
            order.requested_price,
            order.quantity,
            is_buy=order.side == "buy",
        )
        risk_result = self._check_risk(order, execution_price)
        approved_quantity = order.quantity

        if not risk_result.approved and risk_result.adjusted_quantity is not None:
            approved_quantity = risk_result.adjusted_quantity
            adjusted_order = Order(
                order_id=order.order_id,
                signal=order.signal,
                side=order.side,
                quantity=approved_quantity,
                requested_price=order.requested_price,
                created_at=order.created_at,
            )
            execution_price = self.slippage_model.calculate_slippage(
                adjusted_order.requested_price,
                adjusted_order.quantity,
                is_buy=adjusted_order.side == "buy",
            )
            risk_result = self._check_risk(adjusted_order, execution_price)

        decision = self._risk_decision(order, risk_result, approved_quantity)
        self.risk_decisions.append(decision)
        if not decision.approved or decision.approved_quantity is None:
            return None

        quantity = decision.approved_quantity
        commission = self.commission_model.calculate_commission(
            quantity,
            execution_price,
            is_maker=False,
        )
        if order.side == "buy":
            opened = self.portfolio.open_position(
                symbol=order.symbol,
                side="long",
                price=execution_price,
                quantity=quantity,
                timestamp=order.created_at,
                stop_loss=order.signal.stop_loss,
                take_profit=order.signal.take_profit,
                commission=commission,
            )
            if not opened:
                return None
        else:
            pnl = self.portfolio.close_position(
                symbol=order.symbol,
                price=execution_price,
                timestamp=order.created_at,
                commission=commission,
            )
            if pnl is None:
                return None

        fill = Fill(
            fill_id=self._next_id("fill"),
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            price=execution_price,
            commission=commission,
            timestamp=order.created_at,
        )
        self.fills.append(fill)
        return fill

    def _check_risk(self, order: Order, execution_price: Decimal) -> RiskCheckResult:
        current_positions = {
            key: {
                "symbol": position.symbol,
                "side": position.side,
                "value": position.position_value,
            }
            for key, position in self.portfolio.positions.items()
        }
        return self.risk_engine.check_trade(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=execution_price,
            current_balance=self.portfolio.balance,
            current_positions=current_positions,
            total_capital=self.portfolio.total_equity,
            stop_loss_price=order.signal.stop_loss,
        )

    @staticmethod
    def _risk_decision(
        order: Order,
        result: RiskCheckResult,
        approved_quantity: Decimal,
    ) -> RiskDecision:
        return RiskDecision(
            order_id=order.order_id,
            approved=result.approved,
            risk_level=result.risk_level.value,
            codes=tuple(event.value for event in result.events),
            reasons=tuple(result.reasons),
            requested_quantity=order.quantity,
            approved_quantity=approved_quantity if result.approved else None,
        )

    def _calculate_results(self) -> BacktestResult:
        trades = self.portfolio.trade_history
        close_trades = [trade for trade in trades if trade["type"] == "close"]
        result = BacktestResult(
            portfolio=self.portfolio,
            signals=list(self.signals),
            risk_decisions=list(self.risk_decisions),
            orders=list(self.orders),
            fills=list(self.fills),
        )
        result.total_trades = len(close_trades)
        if not close_trades:
            return result

        pnls = [self._decimal(trade["pnl"], "pnl") for trade in close_trades]
        result.total_pnl = sum(pnls, Decimal("0"))
        wins = [pnl for pnl in pnls if pnl > 0]
        losses = [pnl for pnl in pnls if pnl <= 0]
        result.winning_trades = len(wins)
        result.losing_trades = len(losses)
        result.win_rate = Decimal(len(wins)) / Decimal(result.total_trades)
        result.average_win = (
            sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else Decimal("0")
        )
        result.average_loss = (
            sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else Decimal("0")
        )
        result.average_trade = result.total_pnl / Decimal(result.total_trades)
        gross_loss = sum((abs(loss) for loss in losses), Decimal("0"))
        if gross_loss > 0:
            result.profit_factor = sum(wins, Decimal("0")) / gross_loss

        consecutive_losses = 0
        for pnl in pnls:
            consecutive_losses = consecutive_losses + 1 if pnl <= 0 else 0
            result.max_consecutive_losses = max(
                result.max_consecutive_losses,
                consecutive_losses,
            )
        result.max_drawdown = self.portfolio.max_drawdown
        return result

    @staticmethod
    def _as_signal_list(
        signals: Any,
        candle: dict[str, Any],
        timestamp: datetime,
    ) -> list[Signal | dict[str, Any]]:
        if signals is None:
            return []
        if isinstance(signals, (Signal, dict)):
            return [signals]
        return list(signals)

    @staticmethod
    def _normalize_signal(
        signal: Signal | dict[str, Any],
        candle: dict[str, Any],
        timestamp: datetime,
    ) -> Signal:
        if isinstance(signal, Signal):
            return signal
        if is_dataclass(signal) and not isinstance(signal, type):
            raise TypeError("Use app.models.Signal for dataclass strategy signals")
        if not isinstance(signal, dict):
            raise TypeError("Strategy signals must be mappings or app.models.Signal")
        indicators = signal.get("indicators", {})
        metadata = signal.get("metadata", {})
        if not isinstance(indicators, dict):
            raise TypeError("signal.indicators must be a mapping")
        if not isinstance(metadata, dict):
            raise TypeError("signal.metadata must be a mapping")
        return Signal(
            action=str(signal["action"]),
            symbol=str(signal.get("symbol", candle["symbol"])),
            price=BacktestEngine._decimal(signal.get("price", candle["close"]), "price"),
            quantity=BacktestEngine._decimal(signal.get("quantity", "0"), "quantity"),
            timestamp=timestamp,
            reason=str(signal.get("reason", "")),
            stop_loss=BacktestEngine._optional_decimal(signal.get("stop_loss")),
            take_profit=BacktestEngine._optional_decimal(signal.get("take_profit")),
            strategy=str(signal.get("strategy", "")),
            parameters_version=str(signal.get("parameters_version", "")),
            indicators=indicators,
            regime=None if signal.get("regime") is None else str(signal.get("regime")),
            metadata=metadata,
        )

    @staticmethod
    def _indicators_from_candle(candle: dict[str, Any]) -> dict[str, Any]:
        indicators = candle.get("indicators", {})
        if not isinstance(indicators, dict):
            raise TypeError("candle.indicators must be a mapping")
        return indicators

    def _next_id(self, prefix: str) -> str:
        self._sequence += 1
        return f"bt-{prefix}-{self._sequence:08d}"

    @staticmethod
    def _decimal(value: Any, field_name: str) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception as exc:
            raise TypeError(f"{field_name} must be Decimal-compatible") from exc

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        return None if value is None else Decimal(str(value))

    @staticmethod
    def _datetime(value: Any, field_name: str) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError(f"{field_name} must be datetime")
        return value
