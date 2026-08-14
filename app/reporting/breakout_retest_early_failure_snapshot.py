from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade

SNAPSHOT_HOURS = 24


@dataclass(frozen=True)
class EarlyFailureSnapshot:
    symbol: str
    window_index: int
    group: str
    entry_time: datetime
    snapshot_time: datetime
    exit_time: datetime
    exit_reason: str
    realized_pnl: Decimal
    entry_price: Decimal
    close_24h: Decimal
    return_24h_pct: Decimal
    mfe_24h_pct: Decimal
    mae_24h_pct: Decimal
    distance_to_ema20_pct: Decimal | None
    distance_to_ema50_pct: Decimal | None
    distance_to_ema200_pct: Decimal | None
    ema20_slope_1bar_pct: Decimal | None
    ema50_slope_1bar_pct: Decimal | None
    ema200_slope_1bar_pct: Decimal | None
    atr: Decimal | None
    atr_to_close_pct: Decimal | None
    volatility: Decimal | None
    entry_regime: str
    regime_24h: str
    regime_changed_since_entry: bool
    regime_transition_count: int
    regime_confidence_24h: Decimal | None
    breakout_level: Decimal
    distance_to_breakout_level_pct: Decimal


@dataclass(frozen=True)
class SnapshotStats:
    feature: str
    group: str
    count: int
    mean: Decimal | None
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _indicators(candle: dict[str, Any]) -> dict[str, Any]:
    return dict(candle.get("indicators") or {})


def _regime(candle: dict[str, Any]) -> str:
    value = _indicators(candle).get("regime")
    return "UNKNOWN" if value is None else str(value)


def _validate_hourly_sequence(candles: list[dict[str, Any]]) -> None:
    for previous, current in zip(candles, candles[1:]):
        if current["open_time"] - previous["open_time"] != timedelta(hours=1):
            raise ValueError(
                "24h snapshot requires gapless 1h candles: "
                f"{previous['open_time']} -> {current['open_time']}"
            )


def _distance(close: Decimal, value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if value == 0:
        raise ValueError("EMA value must be non-zero")
    return (close - value) / value


def _slope(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None:
        return None
    if previous == 0:
        raise ValueError("Previous EMA value must be non-zero")
    return (current - previous) / previous


def _group(trade: BreakoutRetestTrade) -> str | None:
    if trade.realized_pnl > 0:
        return "FUTURE_WINNER"
    if trade.realized_pnl >= 0:
        return None
    if trade.exit_reason == "Regime changed to TREND_DOWN":
        return "TREND_DOWN_LOSS"
    if trade.exit_reason == "Max holding period reached":
        return "MAX_HOLDING_LOSS"
    return "OTHER_LOSS"


def build_24h_snapshot(
    trade: BreakoutRetestTrade,
    candles: list[dict[str, Any]],
) -> EarlyFailureSnapshot | None:
    """Build one read-only feature snapshot after 24 completed hours.

    The snapshot exists only if the position remains open strictly after the
    close of the 24th hourly candle. No post-snapshot information is used to
    compute features; the final outcome is used only as a diagnostic label.
    """
    ordered = sorted(candles, key=lambda item: item["open_time"])
    _validate_hourly_sequence(ordered)
    by_time = {candle["open_time"]: candle for candle in ordered}

    if trade.entry_fill_time not in by_time:
        raise ValueError(f"Entry candle missing at {trade.entry_fill_time.isoformat()}")

    snapshot_time = trade.entry_fill_time + timedelta(hours=SNAPSHOT_HOURS - 1)
    if snapshot_time >= trade.exit_time:
        return None
    snapshot_candle = by_time.get(snapshot_time)
    if snapshot_candle is None:
        raise ValueError(f"24h snapshot candle missing at {snapshot_time.isoformat()}")

    previous_time = snapshot_time - timedelta(hours=1)
    previous_candle = by_time.get(previous_time)
    if previous_candle is None:
        raise ValueError(f"Previous snapshot candle missing at {previous_time.isoformat()}")

    active = [
        candle
        for candle in ordered
        if trade.entry_fill_time <= candle["open_time"] <= snapshot_time
    ]
    if len(active) != SNAPSHOT_HOURS:
        raise ValueError(
            f"24h snapshot expected {SNAPSHOT_HOURS} candles, got {len(active)}"
        )

    close = _decimal(snapshot_candle["close"])
    highs = [_decimal(candle["high"]) for candle in active]
    lows = [_decimal(candle["low"]) for candle in active]
    maximum = max([trade.entry_price, *highs])
    minimum = min([trade.entry_price, *lows])

    current_ind = _indicators(snapshot_candle)
    previous_ind = _indicators(previous_candle)
    ema20 = _optional_decimal(current_ind.get("ema_20"))
    ema50 = _optional_decimal(current_ind.get("ema_50"))
    ema200 = _optional_decimal(current_ind.get("ema_200"))
    prev_ema20 = _optional_decimal(previous_ind.get("ema_20"))
    prev_ema50 = _optional_decimal(previous_ind.get("ema_50"))
    prev_ema200 = _optional_decimal(previous_ind.get("ema_200"))
    atr = _optional_decimal(current_ind.get("atr"))
    volatility = _optional_decimal(current_ind.get("volatility"))
    regime_confidence = _optional_decimal(current_ind.get("regime_confidence"))

    regimes = [_regime(candle) for candle in active]
    transitions = sum(1 for left, right in zip(regimes, regimes[1:]) if left != right)
    regime_24h = regimes[-1]
    entry_regime = trade.entry_regime

    breakout_level = trade.breakout_level
    if breakout_level <= 0:
        raise ValueError("breakout_level must be positive")

    group = _group(trade)
    if group is None:
        return None

    return EarlyFailureSnapshot(
        symbol=trade.symbol,
        window_index=trade.window_index,
        group=group,
        entry_time=trade.entry_fill_time,
        snapshot_time=snapshot_time,
        exit_time=trade.exit_time,
        exit_reason=trade.exit_reason,
        realized_pnl=trade.realized_pnl,
        entry_price=trade.entry_price,
        close_24h=close,
        return_24h_pct=(close - trade.entry_price) / trade.entry_price,
        mfe_24h_pct=(maximum - trade.entry_price) / trade.entry_price,
        mae_24h_pct=(minimum - trade.entry_price) / trade.entry_price,
        distance_to_ema20_pct=_distance(close, ema20),
        distance_to_ema50_pct=_distance(close, ema50),
        distance_to_ema200_pct=_distance(close, ema200),
        ema20_slope_1bar_pct=_slope(ema20, prev_ema20),
        ema50_slope_1bar_pct=_slope(ema50, prev_ema50),
        ema200_slope_1bar_pct=_slope(ema200, prev_ema200),
        atr=atr,
        atr_to_close_pct=None if atr is None else atr / close,
        volatility=volatility,
        entry_regime=entry_regime,
        regime_24h=regime_24h,
        regime_changed_since_entry=regime_24h != entry_regime,
        regime_transition_count=transitions,
        regime_confidence_24h=regime_confidence,
        breakout_level=breakout_level,
        distance_to_breakout_level_pct=(close - breakout_level) / breakout_level,
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


def _stats(feature: str, group: str, values: list[Decimal]) -> SnapshotStats:
    return SnapshotStats(
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


def build_snapshot_stats(
    snapshots: tuple[EarlyFailureSnapshot, ...],
) -> tuple[SnapshotStats, ...]:
    """Descriptive-only statistics; no thresholds or recommendations."""
    group_predicates: dict[str, Callable[[EarlyFailureSnapshot], bool]] = {
        "FUTURE_WINNER": lambda item: item.group == "FUTURE_WINNER",
        "TREND_DOWN_LOSS": lambda item: item.group == "TREND_DOWN_LOSS",
        "MAX_HOLDING_LOSS": lambda item: item.group == "MAX_HOLDING_LOSS",
        "ALL_LOSERS": lambda item: item.realized_pnl < 0,
        "ALL": lambda item: True,
    }
    features: dict[str, Callable[[EarlyFailureSnapshot], Decimal | None]] = {
        "return_24h_pct": lambda item: item.return_24h_pct,
        "mfe_24h_pct": lambda item: item.mfe_24h_pct,
        "mae_24h_pct": lambda item: item.mae_24h_pct,
        "distance_to_ema20_pct": lambda item: item.distance_to_ema20_pct,
        "distance_to_ema50_pct": lambda item: item.distance_to_ema50_pct,
        "distance_to_ema200_pct": lambda item: item.distance_to_ema200_pct,
        "ema20_slope_1bar_pct": lambda item: item.ema20_slope_1bar_pct,
        "ema50_slope_1bar_pct": lambda item: item.ema50_slope_1bar_pct,
        "ema200_slope_1bar_pct": lambda item: item.ema200_slope_1bar_pct,
        "atr_to_close_pct": lambda item: item.atr_to_close_pct,
        "volatility": lambda item: item.volatility,
        "regime_transition_count": lambda item: Decimal(item.regime_transition_count),
        "regime_changed_since_entry": lambda item: Decimal(int(item.regime_changed_since_entry)),
        "regime_confidence_24h": lambda item: item.regime_confidence_24h,
        "distance_to_breakout_level_pct": lambda item: item.distance_to_breakout_level_pct,
    }

    result: list[SnapshotStats] = []
    for feature, extractor in features.items():
        for group, predicate in group_predicates.items():
            values = [
                value
                for item in snapshots
                if predicate(item) and (value := extractor(item)) is not None
            ]
            result.append(_stats(feature, group, values))
    return tuple(result)


def categorical_counts(
    snapshots: tuple[EarlyFailureSnapshot, ...],
    *,
    group: str,
) -> dict[str, int]:
    selected = [item for item in snapshots if item.group == group]
    result: dict[str, int] = {}
    for item in selected:
        result[item.regime_24h] = result.get(item.regime_24h, 0) + 1
    return dict(sorted(result.items()))
