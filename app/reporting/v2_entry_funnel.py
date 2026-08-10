from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine, BacktestResult
from app.backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardWindow,
    generate_walk_forward_windows,
)
from app.indicators.market_regime import MarketRegime
from app.models import Fill, Signal
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy
from app.strategies.trend_pullback_confirmation import (
    SETUP_TIMEOUT_BARS,
    TrendPullbackConfirmationStrategy,
)

PNL_TOLERANCE = Decimal("1E-12")
QTY_TOLERANCE = Decimal("1E-17")


@dataclass(frozen=True)
class FunnelTrace:
    timestamp: datetime
    phase_before: str
    phase_after: str
    event: str
    cancel_reason: str | None
    bars_since_setup_before: int | None
    bars_since_setup_after: int | None
    rsi_crossed_up: bool
    close_above_ema20: bool
    volatility_ok: bool
    signal_emitted: bool


@dataclass(frozen=True)
class SetupLifecycle:
    setup_time: datetime
    terminal_time: datetime | None
    terminal_reason: str
    bars_since_setup: int
    confirmation_time: datetime | None


@dataclass(frozen=True)
class ReconstructedTrade:
    entry_signal_time: datetime
    entry_fill_time: datetime
    exit_time: datetime
    pnl: Decimal
    exit_reason: str

    @property
    def outcome(self) -> str:
        if self.pnl > 0:
            return "WINNER"
        if self.pnl < 0:
            return "LOSS"
        return "FLAT"


@dataclass(frozen=True)
class BaselineMiss:
    window_index: int
    entry_signal_time: datetime
    entry_fill_time: datetime
    pnl: Decimal
    exit_reason: str
    outcome: str
    v2_status: str


@dataclass(frozen=True)
class WindowFunnel:
    window_index: int
    test_start: datetime
    test_end: datetime
    baseline_trades: int
    baseline_winners: int
    v2_trades: int
    setups_armed: int
    confirmed_signals: int
    confirmed_fills: int
    cancelled_regime: int
    cancelled_close_ema200: int
    cancelled_ema50_ema200: int
    cancelled_position: int
    cancelled_timeout: int
    open_at_end: int
    rsi_crosses_while_armed: int
    rsi_crosses_above_ema20: int
    rsi_crosses_blocked_volatility: int
    waiting_evaluations: int


@dataclass(frozen=True)
class V2EntryFunnelReport:
    symbol: str
    baseline_oos_pnl: Decimal
    v2_oos_pnl: Decimal
    baseline_trades: int
    v2_trades: int
    baseline_winners: int
    baseline_losing_or_flat: int
    setups_armed: int
    confirmed_signals: int
    confirmed_fills: int
    cancelled_regime: int
    cancelled_close_ema200: int
    cancelled_ema50_ema200: int
    cancelled_position: int
    cancelled_timeout: int
    open_at_end: int
    rsi_crosses_while_armed: int
    rsi_crosses_above_ema20: int
    rsi_crosses_blocked_volatility: int
    waiting_evaluations: int
    missed_baseline_winners: tuple[BaselineMiss, ...]
    missed_baseline_losses: tuple[BaselineMiss, ...]
    missed_winner_status_counts: dict[str, int]
    missed_loss_status_counts: dict[str, int]
    windows: tuple[WindowFunnel, ...]


class InstrumentedTrendPullbackConfirmation(TrendPullbackConfirmationStrategy):
    """Read-only diagnostic subclass preserving V2 trading behavior.

    The parent implementation remains the source of truth for every trading
    decision. This subclass only observes state before/after ``should_enter``
    and records the deterministic reason for the observed transition.
    """

    def __init__(self, symbols: list[str]) -> None:
        super().__init__(symbols=symbols)
        self.traces: list[FunnelTrace] = []
        self.lifecycles: list[SetupLifecycle] = []
        self._active_setup_time: dict[str, datetime] = {}
        self._base_fill_count = 0

    @staticmethod
    def _d(value: Any) -> Decimal | None:
        if value is None:
            return None
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @staticmethod
    def _bars(setup: Any) -> int | None:
        if not isinstance(setup, dict):
            return None
        raw = setup.get("bars_since_setup")
        return None if raw is None else int(raw)

    def _infer_cancel_reason(
        self,
        *,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
        setup_before: dict[str, Any],
    ) -> str:
        close = Decimal(str(candle["close"]))
        ema50 = self._d(indicators.get("ema_50"))
        ema200 = self._d(indicators.get("ema_200"))
        regime = indicators.get("regime")
        next_bars = int(setup_before.get("bars_since_setup", 0)) + 1

        # Exact same precedence as the frozen V2 strategy.
        if regime != MarketRegime.TREND_UP:
            return "CANCEL_REGIME"
        if ema200 is not None and close <= ema200:
            return "CANCEL_CLOSE_EMA200"
        if ema50 is not None and ema200 is not None and ema50 <= ema200:
            return "CANCEL_EMA50_EMA200"
        if bool(portfolio_state.get("has_position", False)):
            return "CANCEL_POSITION"
        if next_bars >= SETUP_TIMEOUT_BARS:
            return "CANCEL_TIMEOUT"
        return "CANCEL_UNKNOWN"

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        symbol = str(candle["symbol"])
        timestamp = candle["open_time"]
        if not isinstance(timestamp, datetime):
            raise TypeError("candle.open_time must be datetime")

        state_before = deepcopy(self._symbol_state(symbol))
        phase_before = str(state_before.get("phase") or "IDLE")
        setup_before = state_before.get("setup")
        previous_rsi = self._d(state_before.get("previous_rsi"))
        current_rsi = self._d(indicators.get("rsi"))
        ema20 = self._d(indicators.get("ema_20"))
        close = Decimal(str(candle["close"]))
        volatility = self._d(indicators.get("volatility"))

        crossed_up = bool(
            phase_before == "PULLBACK_ARMED"
            and previous_rsi is not None
            and current_rsi is not None
            and previous_rsi <= Decimal("45")
            and current_rsi > Decimal("45")
        )
        close_above_ema20 = ema20 is not None and close > ema20
        volatility_ok = volatility is None or volatility <= Decimal("0.8")

        signal = super().should_enter(candle, indicators, portfolio_state)

        state_after = deepcopy(self._symbol_state(symbol))
        phase_after = str(state_after.get("phase") or "IDLE")
        setup_after = state_after.get("setup")
        event = "IDLE_NO_SETUP"
        cancel_reason: str | None = None

        if phase_before == "IDLE" and phase_after == "PULLBACK_ARMED":
            event = "SETUP_ARMED"
            self._active_setup_time[symbol] = timestamp
        elif phase_before == "PULLBACK_ARMED" and signal is not None:
            event = "CONFIRMED"
            setup_time = self._active_setup_time.pop(symbol, None)
            if setup_time is None and isinstance(setup_before, dict):
                setup_time = datetime.fromisoformat(str(setup_before["setup_time"]))
            if setup_time is None:
                raise ValueError("Confirmed setup has no recorded setup_time")
            self.lifecycles.append(
                SetupLifecycle(
                    setup_time=setup_time,
                    terminal_time=timestamp,
                    terminal_reason="CONFIRMED",
                    bars_since_setup=int(setup_before.get("bars_since_setup", 0)) + 1,
                    confirmation_time=timestamp,
                )
            )
        elif phase_before == "PULLBACK_ARMED" and phase_after == "IDLE":
            if not isinstance(setup_before, dict):
                raise ValueError("Cancelled setup has no payload")
            cancel_reason = self._infer_cancel_reason(
                candle=candle,
                indicators=indicators,
                portfolio_state=portfolio_state,
                setup_before=setup_before,
            )
            event = cancel_reason
            setup_time = self._active_setup_time.pop(symbol, None)
            if setup_time is None:
                setup_time = datetime.fromisoformat(str(setup_before["setup_time"]))
            self.lifecycles.append(
                SetupLifecycle(
                    setup_time=setup_time,
                    terminal_time=timestamp,
                    terminal_reason=cancel_reason,
                    bars_since_setup=int(setup_before.get("bars_since_setup", 0)) + 1,
                    confirmation_time=None,
                )
            )
        elif phase_before == "PULLBACK_ARMED":
            if crossed_up and close_above_ema20 and not volatility_ok:
                event = "RSI_CROSS_EMA20_VOL_BLOCK"
            elif crossed_up and not close_above_ema20:
                event = "RSI_CROSS_NO_EMA20"
            elif crossed_up and close_above_ema20:
                # Defensive: under current frozen rules this should have confirmed.
                event = "RSI_CROSS_CONFIRMATION_BLOCK_UNKNOWN"
            else:
                event = "WAITING"

        self.traces.append(
            FunnelTrace(
                timestamp=timestamp,
                phase_before=phase_before,
                phase_after=phase_after,
                event=event,
                cancel_reason=cancel_reason,
                bars_since_setup_before=self._bars(setup_before),
                bars_since_setup_after=self._bars(setup_after),
                rsi_crossed_up=crossed_up,
                close_above_ema20=close_above_ema20,
                volatility_ok=volatility_ok,
                signal_emitted=signal is not None,
            )
        )
        return signal

    def on_fill(self, signal: Signal, fill: Fill) -> None:
        super().on_fill(signal, fill)
        if signal.reason == "Trend pullback recovery confirmed" and str(fill.side).lower() == "buy":
            self._base_fill_count += 1

    @property
    def base_fill_count(self) -> int:
        return self._base_fill_count

    def finalize_open_setup(self, symbol: str, terminal_time: datetime) -> None:
        state = self._symbol_state(symbol)
        if state.get("phase") != "PULLBACK_ARMED":
            return
        setup = state.get("setup")
        if not isinstance(setup, dict):
            raise ValueError("Open setup has no payload")
        setup_time = self._active_setup_time.pop(symbol, None)
        if setup_time is None:
            setup_time = datetime.fromisoformat(str(setup["setup_time"]))
        self.lifecycles.append(
            SetupLifecycle(
                setup_time=setup_time,
                terminal_time=terminal_time,
                terminal_reason="OPEN_AT_END",
                bars_since_setup=int(setup.get("bars_since_setup", 0)),
                confirmation_time=None,
            )
        )


def _reconstruct_trades(backtest: BacktestResult) -> list[ReconstructedTrade]:
    signal_by_order = {order.order_id: order.signal for order in backtest.orders}
    quantity = Decimal("0")
    weighted_entry = Decimal("0")
    entry_commission = Decimal("0")
    entry_signal_time: datetime | None = None
    entry_fill_time: datetime | None = None
    records: list[ReconstructedTrade] = []

    for fill in backtest.fills:
        signal = signal_by_order.get(fill.order_id)
        if signal is None:
            raise ValueError(f"Fill has no matching signal: {fill.order_id}")
        side = str(fill.side).lower()
        fill_qty = Decimal(str(fill.quantity))
        fill_price = Decimal(str(fill.price))
        commission = Decimal(str(fill.commission))

        if side == "buy":
            if quantity == 0:
                quantity = fill_qty
                weighted_entry = fill_price
                entry_commission = commission
                entry_signal_time = signal.timestamp
                entry_fill_time = fill.timestamp
            else:
                total_qty = quantity + fill_qty
                weighted_entry = (
                    weighted_entry * quantity + fill_price * fill_qty
                ) / total_qty
                quantity = total_qty
                entry_commission += commission
            continue

        if side != "sell":
            raise ValueError(f"Unsupported fill side: {side}")
        if quantity <= 0 or entry_signal_time is None or entry_fill_time is None:
            raise ValueError("Sell fill without open position")
        if abs(fill_qty - quantity) > QTY_TOLERANCE:
            raise ValueError(
                f"Unexpected partial sell: sell={fill_qty} position={quantity}"
            )

        pnl = (fill_price - weighted_entry) * quantity - entry_commission - commission
        records.append(
            ReconstructedTrade(
                entry_signal_time=entry_signal_time,
                entry_fill_time=entry_fill_time,
                exit_time=fill.timestamp,
                pnl=pnl,
                exit_reason=str(signal.reason or "UNKNOWN"),
            )
        )
        quantity = Decimal("0")
        weighted_entry = Decimal("0")
        entry_commission = Decimal("0")
        entry_signal_time = None
        entry_fill_time = None

    if quantity != 0:
        raise ValueError("Backtest ended with unreconciled open position")
    if len(records) != backtest.total_trades:
        raise ValueError(
            f"Trade reconciliation failed: reconstructed={len(records)} expected={backtest.total_trades}"
        )
    pnl = sum((record.pnl for record in records), Decimal("0"))
    if abs(pnl - backtest.total_pnl) > PNL_TOLERANCE:
        raise ValueError(
            f"PnL reconciliation failed: reconstructed={pnl} expected={backtest.total_pnl}"
        )
    return records


def _trace_status(trace: FunnelTrace | None) -> str:
    if trace is None:
        return "NO_V2_ENTRY_EVALUATION"
    if trace.event == "WAITING":
        return "WAITING"
    return trace.event


def _position_intervals(trades: list[ReconstructedTrade]) -> list[tuple[datetime, datetime]]:
    return [(trade.entry_fill_time, trade.exit_time) for trade in trades]


def _status_for_baseline_entry(
    timestamp: datetime,
    trace_by_time: dict[datetime, FunnelTrace],
    v2_intervals: list[tuple[datetime, datetime]],
) -> str:
    trace = trace_by_time.get(timestamp)
    if trace is not None:
        return _trace_status(trace)
    for start, end in v2_intervals:
        if start <= timestamp <= end:
            return "V2_POSITION_OPEN"
    return "NO_V2_ENTRY_EVALUATION"


def _count_status(items: list[BaselineMiss]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        result[item.v2_status] = result.get(item.v2_status, 0) + 1
    return dict(sorted(result.items()))


def _count_lifecycles(lifecycles: list[SetupLifecycle], reason: str) -> int:
    return sum(item.terminal_reason == reason for item in lifecycles)


def _window_funnel(
    *,
    window: WalkForwardWindow,
    baseline: BacktestResult,
    v2: BacktestResult,
    strategy: InstrumentedTrendPullbackConfirmation,
) -> tuple[WindowFunnel, list[BaselineMiss], list[BaselineMiss]]:
    baseline_trades = _reconstruct_trades(baseline)
    v2_trades = _reconstruct_trades(v2)
    trace_by_time = {trace.timestamp: trace for trace in strategy.traces}
    intervals = _position_intervals(v2_trades)

    v2_signal_times = {
        signal.timestamp
        for signal in v2.signals
        if signal.reason == "Trend pullback recovery confirmed"
    }
    misses_winner: list[BaselineMiss] = []
    misses_loss: list[BaselineMiss] = []
    for trade in baseline_trades:
        # If V2 emitted its own base signal on this exact candle, it did not miss
        # the timing opportunity even if subsequent fills/outcomes differ.
        if trade.entry_signal_time in v2_signal_times:
            continue
        item = BaselineMiss(
            window_index=window.index,
            entry_signal_time=trade.entry_signal_time,
            entry_fill_time=trade.entry_fill_time,
            pnl=trade.pnl,
            exit_reason=trade.exit_reason,
            outcome=trade.outcome,
            v2_status=_status_for_baseline_entry(
                trade.entry_signal_time, trace_by_time, intervals
            ),
        )
        if trade.pnl > 0:
            misses_winner.append(item)
        else:
            misses_loss.append(item)

    traces = strategy.traces
    lifecycles = strategy.lifecycles
    confirmed_signals = sum(trace.event == "CONFIRMED" for trace in traces)
    rsi_crosses = sum(trace.rsi_crossed_up for trace in traces)
    rsi_crosses_ema20 = sum(
        trace.rsi_crossed_up and trace.close_above_ema20 for trace in traces
    )
    volatility_blocks = sum(
        trace.event == "RSI_CROSS_EMA20_VOL_BLOCK" for trace in traces
    )

    window_report = WindowFunnel(
        window_index=window.index,
        test_start=window.test_start,
        test_end=window.test_end,
        baseline_trades=baseline.total_trades,
        baseline_winners=sum(trade.pnl > 0 for trade in baseline_trades),
        v2_trades=v2.total_trades,
        setups_armed=sum(trace.event == "SETUP_ARMED" for trace in traces),
        confirmed_signals=confirmed_signals,
        confirmed_fills=strategy.base_fill_count,
        cancelled_regime=_count_lifecycles(lifecycles, "CANCEL_REGIME"),
        cancelled_close_ema200=_count_lifecycles(lifecycles, "CANCEL_CLOSE_EMA200"),
        cancelled_ema50_ema200=_count_lifecycles(lifecycles, "CANCEL_EMA50_EMA200"),
        cancelled_position=_count_lifecycles(lifecycles, "CANCEL_POSITION"),
        cancelled_timeout=_count_lifecycles(lifecycles, "CANCEL_TIMEOUT"),
        open_at_end=_count_lifecycles(lifecycles, "OPEN_AT_END"),
        rsi_crosses_while_armed=rsi_crosses,
        rsi_crosses_above_ema20=rsi_crosses_ema20,
        rsi_crosses_blocked_volatility=volatility_blocks,
        waiting_evaluations=sum(trace.event == "WAITING" for trace in traces),
    )
    return window_report, misses_winner, misses_loss


def run_v2_entry_funnel(
    *,
    candles: list[dict[str, Any]],
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    config: WalkForwardConfig | None = None,
) -> V2EntryFunnelReport:
    """Run unchanged baseline/V2 OOS windows and report the V2 entry funnel."""
    if interval != "1h":
        raise ValueError("V2 ENTRY FUNNEL diagnostics currently supports only 1h")

    wf_config = config or WalkForwardConfig()
    windows = generate_walk_forward_windows(start, end, wf_config)
    window_reports: list[WindowFunnel] = []
    missed_winners: list[BaselineMiss] = []
    missed_losses: list[BaselineMiss] = []
    baseline_oos_pnl = Decimal("0")
    v2_oos_pnl = Decimal("0")

    for window in windows:
        test_candles = [
            candle
            for candle in candles
            if window.test_start <= candle["open_time"] < window.test_end
        ]
        expected = int((window.test_end - window.test_start).total_seconds() / 3600)
        if len(test_candles) != expected:
            raise ValueError(
                f"Incomplete test window {window.index}: expected={expected} actual={len(test_candles)}"
            )

        baseline_engine = BacktestEngine(
            BacktestConfig(
                initial_balance=wf_config.initial_balance,
                random_seed=wf_config.random_seed,
            )
        )
        baseline = baseline_engine.run(
            candles=test_candles,
            strategy=TrendDCAStrategy([symbol], DCAConfig()),
            indicator_provider=lambda candle, index: candle["indicators"],
        )

        instrumented = InstrumentedTrendPullbackConfirmation([symbol])
        v2_engine = BacktestEngine(
            BacktestConfig(
                initial_balance=wf_config.initial_balance,
                random_seed=wf_config.random_seed,
            )
        )
        v2 = v2_engine.run(
            candles=test_candles,
            strategy=instrumented,
            indicator_provider=lambda candle, index: candle["indicators"],
        )
        instrumented.finalize_open_setup(symbol, window.test_end)

        window_report, window_winners, window_losses = _window_funnel(
            window=window,
            baseline=baseline,
            v2=v2,
            strategy=instrumented,
        )
        window_reports.append(window_report)
        missed_winners.extend(window_winners)
        missed_losses.extend(window_losses)
        baseline_oos_pnl += baseline.total_pnl
        v2_oos_pnl += v2.total_pnl

    return V2EntryFunnelReport(
        symbol=symbol,
        baseline_oos_pnl=baseline_oos_pnl,
        v2_oos_pnl=v2_oos_pnl,
        baseline_trades=sum(item.baseline_trades for item in window_reports),
        v2_trades=sum(item.v2_trades for item in window_reports),
        baseline_winners=sum(item.baseline_winners for item in window_reports),
        baseline_losing_or_flat=(
            sum(item.baseline_trades for item in window_reports)
            - sum(item.baseline_winners for item in window_reports)
        ),
        setups_armed=sum(item.setups_armed for item in window_reports),
        confirmed_signals=sum(item.confirmed_signals for item in window_reports),
        confirmed_fills=sum(item.confirmed_fills for item in window_reports),
        cancelled_regime=sum(item.cancelled_regime for item in window_reports),
        cancelled_close_ema200=sum(item.cancelled_close_ema200 for item in window_reports),
        cancelled_ema50_ema200=sum(item.cancelled_ema50_ema200 for item in window_reports),
        cancelled_position=sum(item.cancelled_position for item in window_reports),
        cancelled_timeout=sum(item.cancelled_timeout for item in window_reports),
        open_at_end=sum(item.open_at_end for item in window_reports),
        rsi_crosses_while_armed=sum(item.rsi_crosses_while_armed for item in window_reports),
        rsi_crosses_above_ema20=sum(item.rsi_crosses_above_ema20 for item in window_reports),
        rsi_crosses_blocked_volatility=sum(
            item.rsi_crosses_blocked_volatility for item in window_reports
        ),
        waiting_evaluations=sum(item.waiting_evaluations for item in window_reports),
        missed_baseline_winners=tuple(missed_winners),
        missed_baseline_losses=tuple(missed_losses),
        missed_winner_status_counts=_count_status(missed_winners),
        missed_loss_status_counts=_count_status(missed_losses),
        windows=tuple(window_reports),
    )
