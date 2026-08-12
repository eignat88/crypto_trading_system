from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any

from app.backtest.commission_model import CommissionModel
from app.backtest.slippage_model import SlippageModel
from app.reporting.breakout_retest_attribution import BreakoutRetestTrade

SNAPSHOT_HOURS = 24
PNL_TOLERANCE = Decimal("1E-24")


@dataclass(frozen=True)
class FailedStructureTradeResult:
    symbol: str
    window_index: int
    entry_fill_time: Any
    actual_exit_time: Any
    actual_exit_reason: str
    actual_pnl: Decimal
    actual_outcome: str
    snapshot_time: Any | None
    snapshot_close: Decimal | None
    snapshot_ema20: Decimal | None
    snapshot_ema50: Decimal | None
    breakout_level: Decimal
    below_ema20: bool | None
    below_ema50: bool | None
    below_breakout_level: bool | None
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
class FailedStructureSummary:
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
    actual_profitable_windows: int
    counterfactual_profitable_windows: int
    leave_one_window_out_min_delta: Decimal
    leave_one_window_out_all_positive: bool
    by_window: tuple[dict[str, Any], ...]
    trades_detail: tuple[FailedStructureTradeResult, ...]


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _trade_seed(base_seed: int, trade: BreakoutRetestTrade) -> int:
    material = (
        f"failed-structure-v1|{base_seed}|{trade.symbol}|{trade.window_index}|"
        f"{trade.entry_fill_time.isoformat()}"
    ).encode("utf-8")
    return int.from_bytes(sha256(material).digest()[:8], "big")


def _validate_hourly(candles: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    ordered = sorted(candles, key=lambda item: item["open_time"])
    for previous, current in zip(ordered, ordered[1:]):
        if current["open_time"] - previous["open_time"] != timedelta(hours=1):
            raise ValueError(
                f"Hourly candle gap: {previous['open_time']} -> {current['open_time']}"
            )
    return {candle["open_time"]: candle for candle in ordered}


def evaluate_failed_structure_trade(
    trade: BreakoutRetestTrade,
    *,
    candles: list[dict[str, Any]],
    base_seed: int = 42,
) -> FailedStructureTradeResult:
    """Evaluate the frozen 24h failed-breakout structure hypothesis read-only.

    The snapshot is the close of the 24th completed hourly candle after entry,
    which has open_time entry+23h. A triggered hypothetical SELL can execute only
    at the following candle open, entry+24h. No future candle contributes to the
    trigger decision.
    """
    by_time = _validate_hourly(candles)
    snapshot_time = trade.entry_fill_time + timedelta(hours=SNAPSHOT_HOURS - 1)
    execution_time = snapshot_time + timedelta(hours=1)
    snapshot = by_time.get(snapshot_time)
    execution_candle = by_time.get(execution_time)

    snapshot_close: Decimal | None = None
    ema20: Decimal | None = None
    ema50: Decimal | None = None
    below_ema20: bool | None = None
    below_ema50: bool | None = None
    below_breakout: bool | None = None
    triggered = False
    hypothetical_reference_price: Decimal | None = None
    hypothetical_execution_price: Decimal | None = None
    hypothetical_commission: Decimal | None = None
    counterfactual_pnl = trade.realized_pnl
    hypothetical_exit_time = None

    if snapshot is not None:
        indicators = snapshot.get("indicators") or {}
        if indicators.get("ema_20") is None or indicators.get("ema_50") is None:
            raise ValueError(
                f"Missing EMA20/EMA50 at frozen 24h snapshot {snapshot_time.isoformat()}"
            )
        snapshot_close = _d(snapshot["close"])
        ema20 = _d(indicators["ema_20"])
        ema50 = _d(indicators["ema_50"])
        below_ema20 = snapshot_close < ema20
        below_ema50 = snapshot_close < ema50
        below_breakout = snapshot_close < trade.breakout_level

    if (
        snapshot is not None
        and execution_candle is not None
        and trade.exit_time > execution_time
        and snapshot_close is not None
        and below_ema20 is True
        and below_ema50 is True
        and below_breakout is True
    ):
        triggered = True
        hypothetical_exit_time = execution_time
        hypothetical_reference_price = _d(
            execution_candle.get("open", execution_candle["close"])
        )
        slippage = SlippageModel(seed=_trade_seed(base_seed, trade))
        hypothetical_execution_price = slippage.calculate_slippage(
            hypothetical_reference_price,
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

    actual_winner = trade.realized_pnl > 0
    counterfactual_winner = counterfactual_pnl > 0
    return FailedStructureTradeResult(
        symbol=trade.symbol,
        window_index=trade.window_index,
        entry_fill_time=trade.entry_fill_time,
        actual_exit_time=trade.exit_time,
        actual_exit_reason=trade.exit_reason,
        actual_pnl=trade.realized_pnl,
        actual_outcome=trade.outcome,
        snapshot_time=snapshot_time if snapshot is not None else None,
        snapshot_close=snapshot_close,
        snapshot_ema20=ema20,
        snapshot_ema50=ema50,
        breakout_level=trade.breakout_level,
        below_ema20=below_ema20,
        below_ema50=below_ema50,
        below_breakout_level=below_breakout,
        triggered=triggered,
        hypothetical_exit_time=hypothetical_exit_time,
        hypothetical_reference_price=hypothetical_reference_price,
        hypothetical_execution_price=hypothetical_execution_price,
        hypothetical_exit_commission=hypothetical_commission,
        counterfactual_pnl=counterfactual_pnl,
        pnl_delta=counterfactual_pnl - trade.realized_pnl,
        sacrificed_winner=actual_winner and not counterfactual_winner,
        saved_loser=trade.realized_pnl < 0 and counterfactual_pnl > trade.realized_pnl,
    )


def build_failed_structure_counterfactual(
    trades: tuple[BreakoutRetestTrade, ...],
    *,
    candles_by_window: dict[int, list[dict[str, Any]]],
    symbol: str,
    base_seed: int = 42,
) -> FailedStructureSummary:
    selected = tuple(trade for trade in trades if trade.symbol == symbol)
    details: list[FailedStructureTradeResult] = []
    for trade in selected:
        candles = candles_by_window.get(trade.window_index)
        if candles is None:
            raise ValueError(f"Missing candles for window {trade.window_index}")
        details.append(
            evaluate_failed_structure_trade(
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

    total_delta = counterfactual_pnl - actual_pnl
    loo_deltas = [
        total_delta - _d(window["pnl_delta"])
        for window in by_window
    ]
    loo_min = min(loo_deltas) if loo_deltas else Decimal("0")

    return FailedStructureSummary(
        symbol=symbol,
        trades=len(details),
        triggered=sum(item.triggered for item in details),
        actual_pnl=actual_pnl,
        counterfactual_pnl=counterfactual_pnl,
        pnl_delta=total_delta,
        actual_winners=sum(item.actual_pnl > 0 for item in details),
        counterfactual_winners=sum(item.counterfactual_pnl > 0 for item in details),
        sacrificed_winners=sum(item.sacrificed_winner for item in details),
        saved_losers=sum(item.saved_loser for item in details),
        actual_profitable_windows=sum(_d(item["actual_pnl"]) > 0 for item in by_window),
        counterfactual_profitable_windows=sum(
            _d(item["counterfactual_pnl"]) > 0 for item in by_window
        ),
        leave_one_window_out_min_delta=loo_min,
        leave_one_window_out_all_positive=bool(loo_deltas) and all(
            value > 0 for value in loo_deltas
        ),
        by_window=tuple(by_window),
        trades_detail=tuple(details),
    )
