from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade
from app.reporting.breakout_retest_early_failure_snapshot import (
    EarlyFailureSnapshot,
    build_24h_snapshot,
)
from app.reporting.breakout_retest_failed_structure_counterfactual import FailedStructureTradeResult


@dataclass(frozen=True)
class FalsePositiveAttributionTrade:
    symbol: str
    window_index: int
    group: str
    entry_time: datetime
    snapshot_time: datetime
    actual_exit_time: datetime
    actual_exit_reason: str
    actual_pnl: Decimal
    counterfactual_pnl: Decimal
    pnl_delta: Decimal
    breakout_strength_pct: Decimal
    retest_depth_pct: Decimal
    bars_to_retest: int
    return_24h_pct: Decimal
    mfe_24h_pct: Decimal
    mae_24h_pct: Decimal
    distance_to_ema20_pct: Decimal | None
    distance_to_ema50_pct: Decimal | None
    distance_to_breakout_level_pct: Decimal
    ema20_slope_1bar_pct: Decimal | None
    ema50_slope_1bar_pct: Decimal | None
    entry_regime: str
    regime_24h: str
    holding_after_24h_bars: int
    future_mfe_after_24h_pct: Decimal
    future_mae_after_24h_pct: Decimal


@dataclass(frozen=True)
class AttributionStats:
    feature: str
    group: str
    count: int
    mean: Decimal | None
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _validate_hourly(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(candles, key=lambda item: item["open_time"])
    for previous, current in zip(ordered, ordered[1:]):
        if current["open_time"] - previous["open_time"] != timedelta(hours=1):
            raise ValueError(
                "False-positive attribution requires gapless 1h candles: "
                f"{previous['open_time']} -> {current['open_time']}"
            )
    return ordered


def _group(result: FailedStructureTradeResult) -> str:
    if not result.triggered:
        raise ValueError("False-positive attribution accepts triggered trades only")
    if result.sacrificed_winner:
        return "SACRIFICED_WINNER"
    if result.saved_loser:
        return "SAVED_LOSER"
    return "OTHER_TRIGGER"


def _future_excursions(
    trade: BreakoutRetestTrade,
    snapshot: EarlyFailureSnapshot,
    candles: list[dict[str, Any]],
) -> tuple[int, Decimal, Decimal]:
    ordered = _validate_hourly(candles)
    start = snapshot.snapshot_time + timedelta(hours=1)
    active = [
        candle for candle in ordered
        if start <= candle["open_time"] < trade.exit_time
    ]
    best = snapshot.close_24h
    worst = snapshot.close_24h
    for candle in active:
        best = max(best, _d(candle["high"]))
        worst = min(worst, _d(candle["low"]))
    # Full OHLC of the actual exit candle is excluded because exit may be intrabar.
    best = max(best, trade.exit_price)
    worst = min(worst, trade.exit_price)
    holding_after = max(0, int((trade.exit_time - start).total_seconds() // 3600))
    return (
        holding_after,
        (best - snapshot.close_24h) / snapshot.close_24h,
        (worst - snapshot.close_24h) / snapshot.close_24h,
    )


def build_false_positive_attribution_trade(
    trade: BreakoutRetestTrade,
    result: FailedStructureTradeResult,
    *,
    candles: list[dict[str, Any]],
) -> FalsePositiveAttributionTrade:
    if result.symbol != trade.symbol or result.window_index != trade.window_index:
        raise ValueError("Trade/result identity mismatch")
    if result.entry_fill_time != trade.entry_fill_time:
        raise ValueError("Trade/result entry timestamp mismatch")
    if not result.triggered:
        raise ValueError("False-positive attribution accepts triggered trades only")

    snapshot = build_24h_snapshot(trade, candles)
    if snapshot is None:
        raise ValueError("Triggered trade has no eligible 24h snapshot")
    if result.snapshot_time != snapshot.snapshot_time:
        raise ValueError("Counterfactual/snapshot 24h timestamp mismatch")

    holding_after, future_mfe, future_mae = _future_excursions(trade, snapshot, candles)
    return FalsePositiveAttributionTrade(
        symbol=trade.symbol,
        window_index=trade.window_index,
        group=_group(result),
        entry_time=trade.entry_fill_time,
        snapshot_time=snapshot.snapshot_time,
        actual_exit_time=trade.exit_time,
        actual_exit_reason=trade.exit_reason,
        actual_pnl=trade.realized_pnl,
        counterfactual_pnl=result.counterfactual_pnl,
        pnl_delta=result.pnl_delta,
        breakout_strength_pct=trade.breakout_strength_pct,
        retest_depth_pct=trade.retest_depth_pct,
        bars_to_retest=trade.bars_to_retest,
        return_24h_pct=snapshot.return_24h_pct,
        mfe_24h_pct=snapshot.mfe_24h_pct,
        mae_24h_pct=snapshot.mae_24h_pct,
        distance_to_ema20_pct=snapshot.distance_to_ema20_pct,
        distance_to_ema50_pct=snapshot.distance_to_ema50_pct,
        distance_to_breakout_level_pct=snapshot.distance_to_breakout_level_pct,
        ema20_slope_1bar_pct=snapshot.ema20_slope_1bar_pct,
        ema50_slope_1bar_pct=snapshot.ema50_slope_1bar_pct,
        entry_regime=snapshot.entry_regime,
        regime_24h=snapshot.regime_24h,
        holding_after_24h_bars=holding_after,
        future_mfe_after_24h_pct=future_mfe,
        future_mae_after_24h_pct=future_mae,
    )


def _percentile(values: list[Decimal], p: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _stats(feature: str, group: str, values: list[Decimal]) -> AttributionStats:
    return AttributionStats(
        feature=feature,
        group=group,
        count=len(values),
        mean=sum(values, Decimal("0")) / Decimal(len(values)) if values else None,
        median=_percentile(values, Decimal("0.5")),
        p25=_percentile(values, Decimal("0.25")),
        p75=_percentile(values, Decimal("0.75")),
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
    )


def build_false_positive_stats(
    items: tuple[FalsePositiveAttributionTrade, ...],
) -> tuple[AttributionStats, ...]:
    groups = ("SAVED_LOSER", "SACRIFICED_WINNER", "OTHER_TRIGGER", "ALL_TRIGGERED")
    features: dict[str, Callable[[FalsePositiveAttributionTrade], Decimal | None]] = {
        "breakout_strength_pct": lambda item: item.breakout_strength_pct,
        "retest_depth_pct": lambda item: item.retest_depth_pct,
        "bars_to_retest": lambda item: Decimal(item.bars_to_retest),
        "return_24h_pct": lambda item: item.return_24h_pct,
        "mfe_24h_pct": lambda item: item.mfe_24h_pct,
        "mae_24h_pct": lambda item: item.mae_24h_pct,
        "distance_to_ema20_pct": lambda item: item.distance_to_ema20_pct,
        "distance_to_ema50_pct": lambda item: item.distance_to_ema50_pct,
        "distance_to_breakout_level_pct": lambda item: item.distance_to_breakout_level_pct,
        "ema20_slope_1bar_pct": lambda item: item.ema20_slope_1bar_pct,
        "ema50_slope_1bar_pct": lambda item: item.ema50_slope_1bar_pct,
        "holding_after_24h_bars": lambda item: Decimal(item.holding_after_24h_bars),
        "future_mfe_after_24h_pct": lambda item: item.future_mfe_after_24h_pct,
        "future_mae_after_24h_pct": lambda item: item.future_mae_after_24h_pct,
    }
    result: list[AttributionStats] = []
    for feature, extractor in features.items():
        for group in groups:
            selected = items if group == "ALL_TRIGGERED" else tuple(
                item for item in items if item.group == group
            )
            values = [value for item in selected if (value := extractor(item)) is not None]
            result.append(_stats(feature, group, values))
    return tuple(result)


def categorical_counts(
    items: tuple[FalsePositiveAttributionTrade, ...],
    *,
    field: str,
    group: str,
) -> dict[str, int]:
    selected = items if group == "ALL_TRIGGERED" else tuple(
        item for item in items if item.group == group
    )
    counts: dict[str, int] = {}
    for item in selected:
        value = str(getattr(item, field))
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
