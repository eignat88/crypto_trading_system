from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from statistics import median
from typing import Any

from app.backtest.backtest_engine import BacktestResult
from app.backtest.ema200_slope_p75_walk_forward import WindowThreshold
from app.backtest.walk_forward import WalkForwardWindow

TD_REASON = "Regime changed to TREND_DOWN"
WIN_REASONS = {"Take-profit hit", "Take profit hit", "Trailing stop hit"}
QTY_TOLERANCE = Decimal("1E-17")


@dataclass(frozen=True)
class CounterfactualTrade:
    symbol: str
    window_index: int
    test_start: datetime
    test_end: datetime
    train_p75: Decimal
    train_opportunities: int
    entry_signal_time: datetime
    entry_fill_time: datetime
    exit_time: datetime
    exit_reason: str
    realized_pnl: Decimal
    outcome_group: str
    filter_group: str
    would_pass_p75: bool
    entry_ema200_slope_10: Decimal
    slope_margin_to_threshold: Decimal
    rsi: Decimal | None
    close_to_ema200: Decimal | None
    ema20_slope_10: Decimal | None
    ema50_slope_10: Decimal | None
    atr_pct: Decimal | None
    volatility: Decimal | None
    regime_confidence: Decimal | None
    trend_up_age_bars: int


@dataclass(frozen=True)
class FeatureSummary:
    trades: int
    average_pnl: Decimal
    average_rsi: Decimal | None
    median_rsi: Decimal | None
    average_close_to_ema200: Decimal | None
    median_close_to_ema200: Decimal | None
    average_ema20_slope_10: Decimal | None
    average_ema50_slope_10: Decimal | None
    average_ema200_slope_10: Decimal | None
    median_ema200_slope_10: Decimal | None
    average_atr_pct: Decimal | None
    average_volatility: Decimal | None
    average_regime_confidence: Decimal | None
    average_trend_up_age_bars: Decimal | None
    median_trend_up_age_bars: Decimal | None


@dataclass(frozen=True)
class CounterfactualReport:
    symbol: str
    trades: tuple[CounterfactualTrade, ...]
    baseline_oos_pnl: Decimal
    total_trades: int
    pass_winner: int
    pass_td_loss: int
    pass_other: int
    filtered_winner: int
    filtered_td_loss: int
    filtered_other: int
    filtered_winner_features: FeatureSummary
    filtered_td_loss_features: FeatureSummary

    @property
    def filtered_total(self) -> int:
        return self.filtered_winner + self.filtered_td_loss + self.filtered_other

    @property
    def filtered_winner_share(self) -> Decimal:
        return Decimal(self.filtered_winner) / Decimal(self.filtered_total) if self.filtered_total else Decimal("0")

    @property
    def filtered_td_loss_share(self) -> Decimal:
        return Decimal(self.filtered_td_loss) / Decimal(self.filtered_total) if self.filtered_total else Decimal("0")


def _d(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _ratio(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    if value is None or base in (None, Decimal("0")):
        return None
    return (value - base) / base


def _avg(values: list[Decimal | None]) -> Decimal | None:
    valid = [value for value in values if value is not None]
    return sum(valid, Decimal("0")) / Decimal(len(valid)) if valid else None


def _median(values: list[Decimal | None]) -> Decimal | None:
    valid = [value for value in values if value is not None]
    return Decimal(str(median(valid))) if valid else None


def _slope_10(candles: list[dict[str, Any]], index: int, indicator_name: str) -> Decimal | None:
    if index < 9:
        return None
    current = _d(candles[index]["indicators"].get(indicator_name))
    past = _d(candles[index - 9]["indicators"].get(indicator_name))
    if current is None or past in (None, Decimal("0")):
        return None
    return (current - past) / past


def _trend_up_age(candles: list[dict[str, Any]], index: int) -> int:
    age = 0
    cursor = index
    while cursor >= 0 and str(candles[cursor]["indicators"].get("regime") or "") == "TREND_UP":
        age += 1
        cursor -= 1
    return age


def _outcome_group(reason: str, pnl: Decimal) -> str:
    if reason == TD_REASON and pnl < 0:
        return "TD_LOSS"
    if reason in WIN_REASONS and pnl > 0:
        return "WINNER"
    return "OTHER"


def reconstruct_window_counterfactual(
    *,
    symbol: str,
    window: WalkForwardWindow,
    threshold: WindowThreshold,
    backtest: BacktestResult,
    all_candles: list[dict[str, Any]],
) -> list[CounterfactualTrade]:
    """Classify baseline TEST trades against the frozen TRAIN p75 threshold.

    The baseline trade outcome is never recomputed. ``would_pass_p75`` is only a
    counterfactual label attached to the original baseline entry signal.
    """
    by_time = {candle["open_time"]: index for index, candle in enumerate(all_candles)}
    signal_by_order_id = {order.order_id: order.signal for order in backtest.orders}

    quantity = Decimal("0")
    weighted_entry = Decimal("0")
    entry_commission = Decimal("0")
    entry_signal = None
    entry_fill_time: datetime | None = None
    records: list[CounterfactualTrade] = []

    for fill in backtest.fills:
        signal = signal_by_order_id.get(fill.order_id)
        if signal is None:
            raise ValueError(f"Fill has no matching order signal: {fill.order_id}")

        side = str(fill.side).lower()
        fill_quantity = Decimal(str(fill.quantity))
        fill_price = Decimal(str(fill.price))
        fill_commission = Decimal(str(fill.commission))

        if side == "buy":
            if quantity == 0:
                quantity = fill_quantity
                weighted_entry = fill_price
                entry_commission = fill_commission
                entry_signal = signal
                entry_fill_time = fill.timestamp
            else:
                total_quantity = quantity + fill_quantity
                weighted_entry = (
                    weighted_entry * quantity + fill_price * fill_quantity
                ) / total_quantity
                quantity = total_quantity
                entry_commission += fill_commission
            continue

        if side != "sell":
            raise ValueError(f"Unsupported fill side: {side}")
        if quantity <= 0 or entry_signal is None or entry_fill_time is None:
            raise ValueError("Sell fill without an open baseline position")
        if abs(fill_quantity - quantity) > QTY_TOLERANCE:
            raise ValueError(
                f"Partial/oversized sell: sell={fill_quantity} position={quantity}"
            )

        pnl = (
            (fill_price - weighted_entry) * quantity
            - entry_commission
            - fill_commission
        )
        reason = str(signal.reason or "UNKNOWN")
        outcome = _outcome_group(reason, pnl)

        entry_time = entry_signal.timestamp
        candle_index = by_time.get(entry_time)
        if candle_index is None:
            raise ValueError(f"Baseline entry signal candle not found: {entry_time}")
        candle = all_candles[candle_index]
        indicators = candle["indicators"]
        ema200_slope = _d(indicators.get("ema200_slope_10"))
        if ema200_slope is None:
            raise ValueError(f"Entry has no ema200_slope_10: {entry_time}")
        would_pass = ema200_slope >= threshold.threshold
        prefix = "PASS" if would_pass else "FILTERED"

        close = _d(candle.get("close"))
        ema200 = _d(indicators.get("ema_200"))
        atr = _d(indicators.get("atr"))
        records.append(
            CounterfactualTrade(
                symbol=symbol,
                window_index=window.index,
                test_start=window.test_start,
                test_end=window.test_end,
                train_p75=threshold.threshold,
                train_opportunities=threshold.train_opportunities,
                entry_signal_time=entry_time,
                entry_fill_time=entry_fill_time,
                exit_time=fill.timestamp,
                exit_reason=reason,
                realized_pnl=pnl,
                outcome_group=outcome,
                filter_group=f"{prefix}_{outcome}",
                would_pass_p75=would_pass,
                entry_ema200_slope_10=ema200_slope,
                slope_margin_to_threshold=ema200_slope - threshold.threshold,
                rsi=_d(indicators.get("rsi")),
                close_to_ema200=_ratio(close, ema200),
                ema20_slope_10=_slope_10(all_candles, candle_index, "ema_20"),
                ema50_slope_10=_slope_10(all_candles, candle_index, "ema_50"),
                atr_pct=(atr / close if atr is not None and close not in (None, Decimal("0")) else None),
                volatility=_d(indicators.get("volatility")),
                regime_confidence=_d(indicators.get("regime_confidence")),
                trend_up_age_bars=_trend_up_age(all_candles, candle_index),
            )
        )

        quantity = Decimal("0")
        weighted_entry = Decimal("0")
        entry_commission = Decimal("0")
        entry_signal = None
        entry_fill_time = None

    if quantity != 0:
        raise ValueError("Baseline audit ended with an open position")
    if len(records) != backtest.total_trades:
        raise ValueError(
            f"Trade count mismatch: reconstructed={len(records)} backtest={backtest.total_trades}"
        )
    return records


def summarize_features(records: list[CounterfactualTrade]) -> FeatureSummary:
    pnl_values = [record.realized_pnl for record in records]
    ages = [Decimal(record.trend_up_age_bars) for record in records]
    return FeatureSummary(
        trades=len(records),
        average_pnl=_avg(pnl_values) or Decimal("0"),
        average_rsi=_avg([record.rsi for record in records]),
        median_rsi=_median([record.rsi for record in records]),
        average_close_to_ema200=_avg([record.close_to_ema200 for record in records]),
        median_close_to_ema200=_median([record.close_to_ema200 for record in records]),
        average_ema20_slope_10=_avg([record.ema20_slope_10 for record in records]),
        average_ema50_slope_10=_avg([record.ema50_slope_10 for record in records]),
        average_ema200_slope_10=_avg([record.entry_ema200_slope_10 for record in records]),
        median_ema200_slope_10=_median([record.entry_ema200_slope_10 for record in records]),
        average_atr_pct=_avg([record.atr_pct for record in records]),
        average_volatility=_avg([record.volatility for record in records]),
        average_regime_confidence=_avg([record.regime_confidence for record in records]),
        average_trend_up_age_bars=_avg(ages),
        median_trend_up_age_bars=_median(ages),
    )


def summarize_counterfactual(
    *, symbol: str, records: list[CounterfactualTrade], baseline_oos_pnl: Decimal
) -> CounterfactualReport:
    counts = {
        name: sum(record.filter_group == name for record in records)
        for name in (
            "PASS_WINNER", "PASS_TD_LOSS", "PASS_OTHER",
            "FILTERED_WINNER", "FILTERED_TD_LOSS", "FILTERED_OTHER",
        )
    }
    filtered_winners = [record for record in records if record.filter_group == "FILTERED_WINNER"]
    filtered_losses = [record for record in records if record.filter_group == "FILTERED_TD_LOSS"]
    return CounterfactualReport(
        symbol=symbol,
        trades=tuple(records),
        baseline_oos_pnl=baseline_oos_pnl,
        total_trades=len(records),
        pass_winner=counts["PASS_WINNER"],
        pass_td_loss=counts["PASS_TD_LOSS"],
        pass_other=counts["PASS_OTHER"],
        filtered_winner=counts["FILTERED_WINNER"],
        filtered_td_loss=counts["FILTERED_TD_LOSS"],
        filtered_other=counts["FILTERED_OTHER"],
        filtered_winner_features=summarize_features(filtered_winners),
        filtered_td_loss_features=summarize_features(filtered_losses),
    )
