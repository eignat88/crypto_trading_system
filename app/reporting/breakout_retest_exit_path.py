from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.reporting.breakout_retest_attribution import BreakoutRetestTrade

HORIZONS_HOURS = (6, 12, 24, 48)


@dataclass(frozen=True)
class HorizonSnapshot:
    horizon_hours: int
    candle_time: datetime
    close: Decimal
    return_pct: Decimal
    regime: str
    ema20: Decimal | None
    ema50: Decimal | None
    ema200: Decimal | None
    close_above_ema20: bool | None
    close_above_ema50: bool | None
    close_above_ema200: bool | None


@dataclass(frozen=True)
class ExitPathTrade:
    symbol: str
    window_index: int
    entry_time: datetime
    exit_time: datetime
    exit_reason: str
    realized_pnl: Decimal
    outcome: str
    entry_price: Decimal
    exit_price: Decimal
    holding_bars: int
    mfe_pct: Decimal
    mae_pct: Decimal
    bars_to_mfe: int
    bars_to_mae: int
    first_trend_down_time: datetime | None
    bars_to_trend_down: int | None
    max_favorable_before_trend_down_pct: Decimal | None
    return_before_trend_down_pct: Decimal | None
    horizons: tuple[HorizonSnapshot, ...]


@dataclass(frozen=True)
class PathStats:
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


def _regime(candle: dict[str, Any]) -> str:
    indicators = candle.get("indicators") or {}
    value = indicators.get("regime")
    return "UNKNOWN" if value is None else str(value)


def _indicator_decimal(candle: dict[str, Any], key: str) -> Decimal | None:
    indicators = candle.get("indicators") or {}
    return _optional_decimal(indicators.get(key))


def _validate_hourly_sequence(candles: list[dict[str, Any]]) -> None:
    for previous, current in zip(candles, candles[1:]):
        delta = current["open_time"] - previous["open_time"]
        if delta != timedelta(hours=1):
            raise ValueError(
                "Exit-path diagnostics require gapless 1h candles: "
                f"{previous['open_time']} -> {current['open_time']}"
            )


def _build_horizon_snapshot(
    trade: BreakoutRetestTrade,
    candles_by_time: dict[datetime, dict[str, Any]],
    horizon_hours: int,
) -> HorizonSnapshot | None:
    # The close of candle entry+(h-1) is exactly h elapsed hourly bars after
    # entry at the first candle open. If the trade exits on that candle or
    # earlier, omit the snapshot to avoid intrabar ordering ambiguity.
    target_time = trade.entry_fill_time + timedelta(hours=horizon_hours - 1)
    if target_time >= trade.exit_time:
        return None
    candle = candles_by_time.get(target_time)
    if candle is None:
        raise ValueError(
            f"Missing candle for {horizon_hours}h snapshot at {target_time.isoformat()}"
        )
    close = _decimal(candle["close"])
    ema20 = _indicator_decimal(candle, "ema_20")
    ema50 = _indicator_decimal(candle, "ema_50")
    ema200 = _indicator_decimal(candle, "ema_200")
    return HorizonSnapshot(
        horizon_hours=horizon_hours,
        candle_time=target_time,
        close=close,
        return_pct=(close - trade.entry_price) / trade.entry_price,
        regime=_regime(candle),
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        close_above_ema20=None if ema20 is None else close > ema20,
        close_above_ema50=None if ema50 is None else close > ema50,
        close_above_ema200=None if ema200 is None else close > ema200,
    )


def analyze_exit_path(
    trade: BreakoutRetestTrade,
    candles: list[dict[str, Any]],
) -> ExitPathTrade:
    """Analyze a closed trade path without changing or re-simulating strategy rules.

    Full OHLC from the exit candle is deliberately excluded from MFE/MAE because
    an intrabar exit may have occurred before the candle's final high/low. The
    actual exit fill price is included as the terminal observation.
    """
    if trade.exit_time < trade.entry_fill_time:
        raise ValueError("Exit precedes entry")
    ordered = sorted(candles, key=lambda item: item["open_time"])
    _validate_hourly_sequence(ordered)
    candles_by_time = {item["open_time"]: item for item in ordered}
    if trade.entry_fill_time not in candles_by_time:
        raise ValueError(f"Entry candle missing at {trade.entry_fill_time.isoformat()}")

    active = [
        candle
        for candle in ordered
        if trade.entry_fill_time <= candle["open_time"] < trade.exit_time
    ]
    if not active and trade.exit_time > trade.entry_fill_time:
        raise ValueError("No active candles between entry and exit")

    best_price = trade.entry_price
    worst_price = trade.entry_price
    bars_to_mfe = 0
    bars_to_mae = 0
    for bar_number, candle in enumerate(active, start=1):
        high = _decimal(candle["high"])
        low = _decimal(candle["low"])
        if high > best_price:
            best_price = high
            bars_to_mfe = bar_number
        if low < worst_price:
            worst_price = low
            bars_to_mae = bar_number

    # The exit fill is a valid observed terminal price even when full exit-candle
    # OHLC is intentionally excluded.
    if trade.exit_price > best_price:
        best_price = trade.exit_price
        bars_to_mfe = max(1, len(active) + 1)
    if trade.exit_price < worst_price:
        worst_price = trade.exit_price
        bars_to_mae = max(1, len(active) + 1)

    first_td_time: datetime | None = None
    bars_to_td: int | None = None
    return_before_td: Decimal | None = None
    max_favorable_before_td: Decimal | None = None
    running_best = trade.entry_price
    for bar_number, candle in enumerate(active, start=1):
        running_best = max(running_best, _decimal(candle["high"]))
        if _regime(candle) == "TREND_DOWN":
            first_td_time = candle["open_time"]
            bars_to_td = bar_number
            return_before_td = (_decimal(candle["close"]) - trade.entry_price) / trade.entry_price
            max_favorable_before_td = (running_best - trade.entry_price) / trade.entry_price
            break

    horizons = tuple(
        snapshot
        for horizon in HORIZONS_HOURS
        if (snapshot := _build_horizon_snapshot(trade, candles_by_time, horizon)) is not None
    )

    return ExitPathTrade(
        symbol=trade.symbol,
        window_index=trade.window_index,
        entry_time=trade.entry_fill_time,
        exit_time=trade.exit_time,
        exit_reason=trade.exit_reason,
        realized_pnl=trade.realized_pnl,
        outcome=trade.outcome,
        entry_price=trade.entry_price,
        exit_price=trade.exit_price,
        holding_bars=trade.holding_bars,
        mfe_pct=(best_price - trade.entry_price) / trade.entry_price,
        mae_pct=(worst_price - trade.entry_price) / trade.entry_price,
        bars_to_mfe=bars_to_mfe,
        bars_to_mae=bars_to_mae,
        first_trend_down_time=first_td_time,
        bars_to_trend_down=bars_to_td,
        max_favorable_before_trend_down_pct=max_favorable_before_td,
        return_before_trend_down_pct=return_before_td,
        horizons=horizons,
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


def _stats(feature: str, group: str, values: list[Decimal]) -> PathStats:
    return PathStats(
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


def build_exit_path_stats(paths: tuple[ExitPathTrade, ...]) -> tuple[PathStats, ...]:
    """Return descriptive-only path statistics for predeclared outcome groups."""
    groups: dict[str, Callable[[ExitPathTrade], bool]] = {
        "WINNER": lambda path: path.outcome == "WINNER",
        "TREND_DOWN_LOSS": lambda path: path.exit_reason == "Regime changed to TREND_DOWN" and path.realized_pnl < 0,
        "MAX_HOLDING_LOSS": lambda path: path.exit_reason == "Max holding period reached" and path.realized_pnl < 0,
        "ALL_LOSERS": lambda path: path.realized_pnl < 0,
        "ALL": lambda path: True,
    }
    features: dict[str, Callable[[ExitPathTrade], Decimal | None]] = {
        "mfe_pct": lambda path: path.mfe_pct,
        "mae_pct": lambda path: path.mae_pct,
        "bars_to_mfe": lambda path: Decimal(path.bars_to_mfe),
        "bars_to_mae": lambda path: Decimal(path.bars_to_mae),
        "bars_to_trend_down": lambda path: None if path.bars_to_trend_down is None else Decimal(path.bars_to_trend_down),
        "max_favorable_before_trend_down_pct": lambda path: path.max_favorable_before_trend_down_pct,
        "return_before_trend_down_pct": lambda path: path.return_before_trend_down_pct,
    }
    for horizon in HORIZONS_HOURS:
        features[f"return_{horizon}h_pct"] = lambda path, h=horizon: next(
            (item.return_pct for item in path.horizons if item.horizon_hours == h),
            None,
        )

    result: list[PathStats] = []
    for feature, extractor in features.items():
        for group, predicate in groups.items():
            values = [
                value
                for path in paths
                if predicate(path) and (value := extractor(path)) is not None
            ]
            result.append(_stats(feature, group, values))
    return tuple(result)
