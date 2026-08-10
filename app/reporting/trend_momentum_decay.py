from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import median
from typing import Any

from app.reporting.entry_filter_counterfactual import CounterfactualReport, CounterfactualTrade

HORIZONS = (6, 12, 24)
TARGET_GROUPS = ("FILTERED_WINNER", "FILTERED_TD_LOSS")


@dataclass(frozen=True)
class MomentumDecayRecord:
    symbol: str
    window_index: int
    filter_group: str
    entry_signal_time: Any
    realized_pnl: Decimal
    horizon_hours: int
    ema20_slope_now: Decimal | None
    ema20_slope_past: Decimal | None
    ema20_slope_delta: Decimal | None
    ema50_slope_now: Decimal | None
    ema50_slope_past: Decimal | None
    ema50_slope_delta: Decimal | None
    ema200_slope_now: Decimal | None
    ema200_slope_past: Decimal | None
    ema200_slope_delta: Decimal | None
    close_to_ema20_now: Decimal | None
    close_to_ema20_past: Decimal | None
    close_to_ema20_delta: Decimal | None
    close_to_ema50_now: Decimal | None
    close_to_ema50_past: Decimal | None
    close_to_ema50_delta: Decimal | None
    close_to_ema200_now: Decimal | None
    close_to_ema200_past: Decimal | None
    close_to_ema200_delta: Decimal | None
    regime_confidence_now: Decimal | None
    regime_confidence_past: Decimal | None
    regime_confidence_delta: Decimal | None


@dataclass(frozen=True)
class MomentumDecaySummary:
    group: str
    horizon_hours: int
    trades: int
    average_pnl: Decimal
    average_ema20_slope_delta: Decimal | None
    median_ema20_slope_delta: Decimal | None
    ema20_decay_count: int
    average_ema50_slope_delta: Decimal | None
    median_ema50_slope_delta: Decimal | None
    ema50_decay_count: int
    average_ema200_slope_delta: Decimal | None
    median_ema200_slope_delta: Decimal | None
    ema200_decay_count: int
    average_close_to_ema20_delta: Decimal | None
    average_close_to_ema50_delta: Decimal | None
    average_close_to_ema200_delta: Decimal | None
    average_regime_confidence_delta: Decimal | None
    confidence_decay_count: int

    @property
    def ema20_decay_rate(self) -> Decimal:
        return Decimal(self.ema20_decay_count) / Decimal(self.trades) if self.trades else Decimal("0")

    @property
    def ema50_decay_rate(self) -> Decimal:
        return Decimal(self.ema50_decay_count) / Decimal(self.trades) if self.trades else Decimal("0")

    @property
    def ema200_decay_rate(self) -> Decimal:
        return Decimal(self.ema200_decay_count) / Decimal(self.trades) if self.trades else Decimal("0")

    @property
    def confidence_decay_rate(self) -> Decimal:
        return Decimal(self.confidence_decay_count) / Decimal(self.trades) if self.trades else Decimal("0")


@dataclass(frozen=True)
class TrendMomentumDecayReport:
    symbol: str
    source_filtered_winners: int
    source_filtered_td_losses: int
    records: tuple[MomentumDecayRecord, ...]
    summaries: tuple[MomentumDecaySummary, ...]


def _d(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _delta(now: Decimal | None, past: Decimal | None) -> Decimal | None:
    if now is None or past is None:
        return None
    return now - past


def _ratio(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    if value is None or base in (None, Decimal("0")):
        return None
    return (value - base) / base


def _slope_10(candles: list[dict[str, Any]], index: int, key: str) -> Decimal | None:
    if index < 9:
        return None
    current = _d(candles[index]["indicators"].get(key))
    past = _d(candles[index - 9]["indicators"].get(key))
    if current is None or past in (None, Decimal("0")):
        return None
    return (current - past) / past


def _avg(values: list[Decimal | None]) -> Decimal | None:
    valid = [value for value in values if value is not None]
    return sum(valid, Decimal("0")) / Decimal(len(valid)) if valid else None


def _median(values: list[Decimal | None]) -> Decimal | None:
    valid = [value for value in values if value is not None]
    return Decimal(str(median(valid))) if valid else None


def _distance(candle: dict[str, Any], ema_key: str) -> Decimal | None:
    close = _d(candle.get("close"))
    ema = _d(candle["indicators"].get(ema_key))
    return _ratio(close, ema)


def build_trend_momentum_decay(
    *,
    candles: list[dict[str, Any]],
    counterfactual: CounterfactualReport,
    horizons: tuple[int, ...] = HORIZONS,
) -> TrendMomentumDecayReport:
    """Compare pre-entry momentum change for filtered winners vs filtered TD losses.

    All values are causal: each entry uses only its candle and earlier candles.
    ``delta`` is defined as entry value minus the value exactly ``h`` 1h candles
    earlier. No outcome-dependent threshold is derived here.
    """
    if any(horizon <= 0 for horizon in horizons):
        raise ValueError("Horizons must be positive")

    ordered = sorted(candles, key=lambda candle: candle["open_time"])
    by_time = {candle["open_time"]: index for index, candle in enumerate(ordered)}
    selected = [trade for trade in counterfactual.trades if trade.filter_group in TARGET_GROUPS]
    records: list[MomentumDecayRecord] = []

    for trade in selected:
        entry_index = by_time.get(trade.entry_signal_time)
        if entry_index is None:
            raise ValueError(f"Entry candle not found: {trade.entry_signal_time}")

        for horizon in horizons:
            past_index = entry_index - horizon
            if past_index < 9:
                raise ValueError(
                    f"Insufficient causal history for {trade.entry_signal_time} horizon={horizon}h"
                )
            now = ordered[entry_index]
            past = ordered[past_index]

            ema20_now = _slope_10(ordered, entry_index, "ema_20")
            ema20_past = _slope_10(ordered, past_index, "ema_20")
            ema50_now = _slope_10(ordered, entry_index, "ema_50")
            ema50_past = _slope_10(ordered, past_index, "ema_50")
            ema200_now = _slope_10(ordered, entry_index, "ema_200")
            ema200_past = _slope_10(ordered, past_index, "ema_200")

            d20_now = _distance(now, "ema_20")
            d20_past = _distance(past, "ema_20")
            d50_now = _distance(now, "ema_50")
            d50_past = _distance(past, "ema_50")
            d200_now = _distance(now, "ema_200")
            d200_past = _distance(past, "ema_200")
            confidence_now = _d(now["indicators"].get("regime_confidence"))
            confidence_past = _d(past["indicators"].get("regime_confidence"))

            records.append(
                MomentumDecayRecord(
                    symbol=trade.symbol,
                    window_index=trade.window_index,
                    filter_group=trade.filter_group,
                    entry_signal_time=trade.entry_signal_time,
                    realized_pnl=trade.realized_pnl,
                    horizon_hours=horizon,
                    ema20_slope_now=ema20_now,
                    ema20_slope_past=ema20_past,
                    ema20_slope_delta=_delta(ema20_now, ema20_past),
                    ema50_slope_now=ema50_now,
                    ema50_slope_past=ema50_past,
                    ema50_slope_delta=_delta(ema50_now, ema50_past),
                    ema200_slope_now=ema200_now,
                    ema200_slope_past=ema200_past,
                    ema200_slope_delta=_delta(ema200_now, ema200_past),
                    close_to_ema20_now=d20_now,
                    close_to_ema20_past=d20_past,
                    close_to_ema20_delta=_delta(d20_now, d20_past),
                    close_to_ema50_now=d50_now,
                    close_to_ema50_past=d50_past,
                    close_to_ema50_delta=_delta(d50_now, d50_past),
                    close_to_ema200_now=d200_now,
                    close_to_ema200_past=d200_past,
                    close_to_ema200_delta=_delta(d200_now, d200_past),
                    regime_confidence_now=confidence_now,
                    regime_confidence_past=confidence_past,
                    regime_confidence_delta=_delta(confidence_now, confidence_past),
                )
            )

    summaries: list[MomentumDecaySummary] = []
    for group in TARGET_GROUPS:
        for horizon in horizons:
            items = [
                record
                for record in records
                if record.filter_group == group and record.horizon_hours == horizon
            ]
            summaries.append(
                MomentumDecaySummary(
                    group=group,
                    horizon_hours=horizon,
                    trades=len(items),
                    average_pnl=_avg([item.realized_pnl for item in items]) or Decimal("0"),
                    average_ema20_slope_delta=_avg([item.ema20_slope_delta for item in items]),
                    median_ema20_slope_delta=_median([item.ema20_slope_delta for item in items]),
                    ema20_decay_count=sum(item.ema20_slope_delta is not None and item.ema20_slope_delta < 0 for item in items),
                    average_ema50_slope_delta=_avg([item.ema50_slope_delta for item in items]),
                    median_ema50_slope_delta=_median([item.ema50_slope_delta for item in items]),
                    ema50_decay_count=sum(item.ema50_slope_delta is not None and item.ema50_slope_delta < 0 for item in items),
                    average_ema200_slope_delta=_avg([item.ema200_slope_delta for item in items]),
                    median_ema200_slope_delta=_median([item.ema200_slope_delta for item in items]),
                    ema200_decay_count=sum(item.ema200_slope_delta is not None and item.ema200_slope_delta < 0 for item in items),
                    average_close_to_ema20_delta=_avg([item.close_to_ema20_delta for item in items]),
                    average_close_to_ema50_delta=_avg([item.close_to_ema50_delta for item in items]),
                    average_close_to_ema200_delta=_avg([item.close_to_ema200_delta for item in items]),
                    average_regime_confidence_delta=_avg([item.regime_confidence_delta for item in items]),
                    confidence_decay_count=sum(item.regime_confidence_delta is not None and item.regime_confidence_delta < 0 for item in items),
                )
            )

    return TrendMomentumDecayReport(
        symbol=counterfactual.symbol,
        source_filtered_winners=counterfactual.filtered_winner,
        source_filtered_td_losses=counterfactual.filtered_td_loss,
        records=tuple(records),
        summaries=tuple(summaries),
    )
