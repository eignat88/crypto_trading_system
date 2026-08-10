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
RULE_NAME = "breakout_structural_failure_counterfactual_v1"


@dataclass(frozen=True)
class StructuralFailureTradeResult:
    symbol: str
    window_index: int
    entry_fill_time: Any
    actual_exit_time: Any
    actual_exit_reason: str
    actual_pnl: Decimal
    actual_outcome: str
    snapshot_time: Any | None
    close_24h: Decimal | None
    breakout_level: Decimal
    ema20_24h: Decimal | None
    ema20_previous: Decimal | None
    below_breakout_level: bool | None
    below_ema20: bool | None
    ema20_falling: bool | None
    triggered: bool
    hypothetical_exit_time: Any | None
    hypothetical_reference_price: Decimal | None
    hypothetical_execution_price: Decimal | None
    hypothetical_exit_commission: Decimal | None
    counterfactual_pnl: Decimal
    pnl_delta: Decimal
    sacrificed_winner: bool
    saved_loser: bool
    saved_trend_down_loss: bool


@dataclass(frozen=True)
class StructuralFailureSummary:
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
    saved_trend_down_losses: int
    triggered_trend_down_losses: int
    triggered_max_holding_losses: int
    positive_delta_windows: int
    by_window: tuple[dict[str, Any], ...]
    trades_detail: tuple[StructuralFailureTradeResult, ...]


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _ema20(candle: dict[str, Any]) -> Decimal | None:
    indicators = candle.get("indicators") or {}
    value = indicators.get("ema_20")
    return None if value is None else _d(value)


def _trade_seed(base_seed: int, trade: BreakoutRetestTrade) -> int:
    material = (
        f"{base_seed}|{RULE_NAME}|{trade.symbol}|{trade.window_index}|"
        f"{trade.entry_fill_time.isoformat()}"
    ).encode("utf-8")
    return int.from_bytes(sha256(material).digest()[:8], "big")


def _validate_hourly(candles: list[dict[str, Any]]) -> dict[Any, dict[str, Any]]:
    ordered = sorted(candles, key=lambda item: item["open_time"])
    for previous, current in zip(ordered, ordered[1:]):
        if current["open_time"] - previous["open_time"] != timedelta(hours=1):
            raise ValueError(
                "Structural-failure counterfactual requires gapless 1h candles: "
                f"{previous['open_time']} -> {current['open_time']}"
            )
    return {candle["open_time"]: candle for candle in ordered}


def evaluate_structural_failure_trade(
    trade: BreakoutRetestTrade,
    *,
    candles: list[dict[str, Any]],
    base_seed: int = 42,
) -> StructuralFailureTradeResult:
    """Evaluate the single frozen v1 structural-failure rule without strategy changes."""
    by_time = _validate_hourly(candles)

    # Entry occurs at an hourly candle open. The close of entry+(24-1) is the
    # close after exactly 24 completed hourly bars. Only after that close is the
    # frozen condition known; a hypothetical sell may execute at N+1 open.
    snapshot_time = trade.entry_fill_time + timedelta(hours=HORIZON_HOURS - 1)
    previous_time = snapshot_time - timedelta(hours=1)
    execution_time = snapshot_time + timedelta(hours=1)

    snapshot = by_time.get(snapshot_time)
    previous = by_time.get(previous_time)
    execution_candle = by_time.get(execution_time)

    close_24h: Decimal | None = None
    ema20_24h: Decimal | None = None
    ema20_previous: Decimal | None = None
    below_breakout: bool | None = None
    below_ema20: bool | None = None
    ema20_falling: bool | None = None
    triggered = False
    reference_price: Decimal | None = None
    execution_price: Decimal | None = None
    commission: Decimal | None = None
    counterfactual_pnl = trade.realized_pnl
    hypothetical_exit_time: Any | None = None

    if snapshot is not None:
        close_24h = _d(snapshot["close"])
        ema20_24h = _ema20(snapshot)
    if previous is not None:
        ema20_previous = _ema20(previous)

    if close_24h is not None:
        below_breakout = close_24h < trade.breakout_level
    if close_24h is not None and ema20_24h is not None:
        below_ema20 = close_24h < ema20_24h
    if ema20_24h is not None and ema20_previous is not None:
        ema20_falling = ema20_24h < ema20_previous

    condition = (
        below_breakout is True
        and below_ema20 is True
        and ema20_falling is True
    )

    if (
        condition
        and execution_candle is not None
        and trade.exit_time > execution_time
    ):
        triggered = True
        hypothetical_exit_time = execution_time
        reference_price = _d(execution_candle.get("open", execution_candle["close"]))
        slippage = SlippageModel(seed=_trade_seed(base_seed, trade))
        execution_price = slippage.calculate_slippage(
            reference_price,
            trade.quantity,
            is_buy=False,
        )
        commission = CommissionModel().calculate_commission(
            trade.quantity,
            execution_price,
            is_maker=False,
        )
        counterfactual_pnl = (
            (execution_price - trade.entry_price) * trade.quantity
            - trade.entry_commission
            - commission
        )

    actual_winner = trade.realized_pnl > 0
    counterfactual_winner = counterfactual_pnl > 0
    saved_loser = trade.realized_pnl < 0 and counterfactual_pnl > trade.realized_pnl
    saved_td = (
        saved_loser and trade.exit_reason == "Regime changed to TREND_DOWN"
    )

    return StructuralFailureTradeResult(
        symbol=trade.symbol,
        window_index=trade.window_index,
        entry_fill_time=trade.entry_fill_time,
        actual_exit_time=trade.exit_time,
        actual_exit_reason=trade.exit_reason,
        actual_pnl=trade.realized_pnl,
        actual_outcome=trade.outcome,
        snapshot_time=snapshot_time if snapshot is not None else None,
        close_24h=close_24h,
        breakout_level=trade.breakout_level,
        ema20_24h=ema20_24h,
        ema20_previous=ema20_previous,
        below_breakout_level=below_breakout,
        below_ema20=below_ema20,
        ema20_falling=ema20_falling,
        triggered=triggered,
        hypothetical_exit_time=hypothetical_exit_time,
        hypothetical_reference_price=reference_price,
        hypothetical_execution_price=execution_price,
        hypothetical_exit_commission=commission,
        counterfactual_pnl=counterfactual_pnl,
        pnl_delta=counterfactual_pnl - trade.realized_pnl,
        sacrificed_winner=actual_winner and not counterfactual_winner,
        saved_loser=saved_loser,
        saved_trend_down_loss=saved_td,
    )


def build_structural_failure_counterfactual(
    trades: tuple[BreakoutRetestTrade, ...],
    *,
    candles_by_window: dict[int, list[dict[str, Any]]],
    symbol: str,
    base_seed: int = 42,
) -> StructuralFailureSummary:
    selected = tuple(trade for trade in trades if trade.symbol == symbol)
    details: list[StructuralFailureTradeResult] = []
    for trade in selected:
        candles = candles_by_window.get(trade.window_index)
        if candles is None:
            raise ValueError(f"Missing candles for window {trade.window_index}")
        details.append(
            evaluate_structural_failure_trade(
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
                "saved_trend_down_losses": sum(
                    item.saved_trend_down_loss for item in group
                ),
            }
        )

    return StructuralFailureSummary(
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
        saved_trend_down_losses=sum(item.saved_trend_down_loss for item in details),
        triggered_trend_down_losses=sum(
            item.triggered
            and item.actual_exit_reason == "Regime changed to TREND_DOWN"
            and item.actual_pnl < 0
            for item in details
        ),
        triggered_max_holding_losses=sum(
            item.triggered
            and item.actual_exit_reason == "Max holding period reached"
            and item.actual_pnl < 0
            for item in details
        ),
        positive_delta_windows=sum(
            item["pnl_delta"] > 0 for item in by_window
        ),
        by_window=tuple(by_window),
        trades_detail=tuple(details),
    )
