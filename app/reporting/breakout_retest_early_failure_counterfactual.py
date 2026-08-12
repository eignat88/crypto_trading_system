from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from app.backtest.commission_model import CommissionModel
from app.backtest.slippage_model import SlippageModel
from app.reporting.breakout_retest_attribution import BreakoutRetestTrade

HORIZON_HOURS = 24
PNL_TOLERANCE = Decimal("1E-24")


@dataclass(frozen=True)
class EarlyFailureTradeResult:
    symbol: str
    window_index: int
    entry_fill_time: Any
    actual_exit_time: Any
    actual_exit_reason: str
    actual_pnl: Decimal
    actual_outcome: str
    horizon_time: Any | None
    horizon_close: Decimal | None
    triggered: bool
    hypothetical_exit_time: Any | None
    hypothetical_reference_price: Decimal | None
    hypothetical_execution_price: Decimal | None
    hypothetical_exit_commission: Decimal | None
    counterfactual_pnl: Decimal
    pnl_delta: Decimal
    sacrificed_winner: bool
    saved_loser: bool


@dataclass(frozen=True)
class CounterfactualSummary:
    symbol: str
    trades: int
    triggered: int
    actual_pnl: Decimal
    counterfactual_pnl: Decimal
    pnl_delta: Decimal
    actual_winners: int
    counterfactual_winners: int
    sacrificed_winners: int
    saved_losers: int
    by_window: tuple[dict[str, Any], ...]
    trades_detail: tuple[EarlyFailureTradeResult, ...]


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _trade_seed(base_seed: int, trade: BreakoutRetestTrade) -> int:
    material = (
        f"{base_seed}|{trade.symbol}|{trade.window_index}|"
        f"{trade.entry_fill_time.isoformat()}"
    ).encode()
    return int.from_bytes(sha256(material).digest()[:8], "big")


def _validate_hourly(candles: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    ordered = sorted(candles, key=lambda c: c["open_time"])
    for prev, cur in zip(ordered, ordered[1:]):
        if cur["open_time"] - prev["open_time"] != timedelta(hours=1):
            raise ValueError(
                f"Hourly candle gap: {prev['open_time']} -> {cur['open_time']}"
            )
    return {candle["open_time"]: candle for candle in ordered}


def evaluate_early_failure_trade(
    trade: BreakoutRetestTrade,
    *,
    candles: list[dict[str, Any]],
    base_seed: int = 42,
) -> EarlyFailureTradeResult:
    by_time = _validate_hourly(candles)
    horizon_time = trade.entry_fill_time + timedelta(hours=HORIZON_HOURS)
    horizon = by_time.get(horizon_time)

    # The condition is evaluated at the close of the 24th hourly candle after
    # entry. Execution can happen only at the next candle open.
    execution_time = horizon_time + timedelta(hours=1)
    execution_candle = by_time.get(execution_time)

    horizon_close: Decimal | None = None
    triggered = False
    hypothetical_execution_price: Decimal | None = None
    hypothetical_commission: Decimal | None = None
    counterfactual_pnl = trade.realized_pnl

    if horizon is not None:
        horizon_close = _d(horizon["close"])

    if (
        horizon is not None
        and execution_candle is not None
        and trade.exit_time > execution_time
        and horizon_close is not None
        and horizon_close < trade.entry_price
    ):
        triggered = True
        reference_price = _d(execution_candle.get("open", execution_candle["close"]))
        slippage = SlippageModel(seed=_trade_seed(base_seed, trade))
        hypothetical_execution_price = slippage.calculate_slippage(
            reference_price,
            trade.quantity,
            is_buy=False,
        )
        hypothetical_commission = CommissionModel().calculate_commission(
            trade.quantity,
            hypothetical_execution_price,
            is_maker=False,
        )
        counterfactual_pnl = (
            (hypothetical_execution_price - trade.entry_price) * trade.quantity
            - trade.entry_commission
            - hypothetical_commission
        )
    else:
        reference_price = None
        execution_time = None

    actual_winner = trade.realized_pnl > 0
    counterfactual_winner = counterfactual_pnl > 0
    return EarlyFailureTradeResult(
        symbol=trade.symbol,
        window_index=trade.window_index,
        entry_fill_time=trade.entry_fill_time,
        actual_exit_time=trade.exit_time,
        actual_exit_reason=trade.exit_reason,
        actual_pnl=trade.realized_pnl,
        actual_outcome=trade.outcome,
        horizon_time=horizon_time if horizon is not None else None,
        horizon_close=horizon_close,
        triggered=triggered,
        hypothetical_exit_time=execution_time,
        hypothetical_reference_price=reference_price,
        hypothetical_execution_price=hypothetical_execution_price,
        hypothetical_exit_commission=hypothetical_commission,
        counterfactual_pnl=counterfactual_pnl,
        pnl_delta=counterfactual_pnl - trade.realized_pnl,
        sacrificed_winner=actual_winner and not counterfactual_winner,
        saved_loser=(trade.realized_pnl < 0 and counterfactual_pnl > trade.realized_pnl),
    )


def build_early_failure_counterfactual(
    trades: tuple[BreakoutRetestTrade, ...],
    *,
    candles_by_window: dict[int, list[dict[str, Any]]],
    symbol: str,
    base_seed: int = 42,
) -> CounterfactualSummary:
    selected = tuple(trade for trade in trades if trade.symbol == symbol)
    details: list[EarlyFailureTradeResult] = []
    for trade in selected:
        candles = candles_by_window.get(trade.window_index)
        if candles is None:
            raise ValueError(f"Missing candles for window {trade.window_index}")
        details.append(
            evaluate_early_failure_trade(
                trade,
                candles=candles,
                base_seed=base_seed,
            )
        )

    actual_pnl = sum((item.actual_pnl for item in details), Decimal("0"))
    counterfactual_pnl = sum(
        (item.counterfactual_pnl for item in details), Decimal("0")
    )

    by_window: list[dict[str, Any]] = []
    for window_index in sorted({item.window_index for item in details}):
        group = [item for item in details if item.window_index == window_index]
        actual = sum((item.actual_pnl for item in group), Decimal("0"))
        counterfactual = sum(
            (item.counterfactual_pnl for item in group), Decimal("0")
        )
        by_window.append(
            {
                "window_index": window_index,
                "trades": len(group),
                "triggered": sum(item.triggered for item in group),
                "actual_pnl": actual,
                "counterfactual_pnl": counterfactual,
                "pnl_delta": counterfactual - actual,
                "sacrificed_winners": sum(item.sacrificed_winner for item in group),
                "saved_losers": sum(item.saved_loser for item in group),
            }
        )

    return CounterfactualSummary(
        symbol=symbol,
        trades=len(details),
        triggered=sum(item.triggered for item in details),
        actual_pnl=actual_pnl,
        counterfactual_pnl=counterfactual_pnl,
        pnl_delta=counterfactual_pnl - actual_pnl,
        actual_winners=sum(item.actual_pnl > 0 for item in details),
        counterfactual_winners=sum(item.counterfactual_pnl > 0 for item in details),
        sacrificed_winners=sum(item.sacrificed_winner for item in details),
        saved_losers=sum(item.saved_loser for item in details),
        by_window=tuple(by_window),
        trades_detail=tuple(details),
    )
