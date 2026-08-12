from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from statistics import median
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.connection import async_session_factory

TD_REASON = "Regime changed to TREND_DOWN"
WIN_REASONS = {"Take-profit hit", "Take profit hit", "Trailing stop hit"}
QTY_TOLERANCE = Decimal("1E-17")


@dataclass(frozen=True)
class EntryQualityRecord:
    run_id: UUID
    symbol: str
    outcome_group: str
    exit_reason: str
    entry_signal_time: datetime
    entry_fill_time: datetime
    entry_signal_price: Decimal
    entry_fill_price: Decimal
    weighted_entry_price: Decimal
    dca_count: int
    rsi: Decimal | None
    ema_20: Decimal | None
    ema_50: Decimal | None
    ema_200: Decimal | None
    close_to_ema20: Decimal | None
    close_to_ema50: Decimal | None
    close_to_ema200: Decimal | None
    ema20_slope_10: Decimal | None
    ema50_slope_10: Decimal | None
    ema200_slope_10: Decimal | None
    atr: Decimal | None
    atr_pct: Decimal | None
    volatility: Decimal | None
    regime_confidence: Decimal | None
    trend_up_age_bars: int
    trend_up_age_censored: bool
    time_to_trend_down_hours: Decimal | None
    trend_down_before_exit: bool
    exit_time: datetime
    realized_pnl: Decimal


@dataclass(frozen=True)
class EntryQualityGroupSummary:
    group: str
    trades: int
    average_pnl: Decimal
    average_rsi: Decimal | None
    median_rsi: Decimal | None
    average_close_to_ema20: Decimal | None
    average_close_to_ema50: Decimal | None
    average_close_to_ema200: Decimal | None
    average_ema20_slope_10: Decimal | None
    average_ema50_slope_10: Decimal | None
    average_ema200_slope_10: Decimal | None
    average_atr_pct: Decimal | None
    average_volatility: Decimal | None
    average_regime_confidence: Decimal | None
    average_trend_up_age_bars: Decimal
    median_trend_up_age_bars: Decimal
    trend_down_before_exit: int
    average_time_to_trend_down_hours: Decimal | None


@dataclass(frozen=True)
class EntryQualityReport:
    run_id: UUID
    symbol: str
    interval: str
    records: tuple[EntryQualityRecord, ...]
    trend_down_losses: EntryQualityGroupSummary
    winners: EntryQualityGroupSummary
    other_trades: int


def _d(value: Any) -> Decimal | None:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _json(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _ratio(value: Decimal | None, base: Decimal | None) -> Decimal | None:
    if value is None or base in (None, Decimal("0")):
        return None
    return (value - base) / base


def _slope(rows: list[dict[str, Any]], idx: int, key: str, lookback: int = 10) -> Decimal | None:
    start = idx - (lookback - 1)
    if start < 0:
        return None
    current = _d(rows[idx].get(key))
    past = _d(rows[start].get(key))
    if current is None or past in (None, Decimal("0")):
        return None
    return (current - past) / past


def _avg(values: list[Decimal | None]) -> Decimal | None:
    valid = [v for v in values if v is not None]
    return sum(valid, Decimal("0")) / Decimal(len(valid)) if valid else None


def _median(values: list[Decimal | None]) -> Decimal | None:
    valid = [v for v in values if v is not None]
    return Decimal(str(median(valid))) if valid else None


def _classify_exit(reason: str, realized_pnl: Decimal) -> str:
    if reason == TD_REASON:
        return "TREND_DOWN_LOSS"
    if reason in WIN_REASONS and realized_pnl > 0:
        return "WINNER"
    return "OTHER"


def reconstruct_entry_quality(
    *, run_id: UUID, symbol: str, fill_rows: list[dict[str, Any]], candle_rows: list[dict[str, Any]]
) -> list[EntryQualityRecord]:
    candle_rows = sorted(candle_rows, key=lambda r: _utc(r["open_time"]))
    by_time = {_utc(row["open_time"]): idx for idx, row in enumerate(candle_rows)}
    records: list[EntryQualityRecord] = []
    qty = Decimal("0")
    weighted = Decimal("0")
    entry_fee = Decimal("0")
    entry_signal: dict[str, Any] | None = None
    entry_fill_time: datetime | None = None
    entry_fill_price = Decimal("0")
    buy_count = 0

    for row in fill_rows:
        side = str(row["side"]).lower()
        q, price, fee = _d(row["quantity"]), _d(row["price"]), _d(row["commission"])
        if q is None or price is None or fee is None:
            raise ValueError("Fill contains NULL numeric value")
        signal = _json(row.get("signal"))
        fill_time = _utc(row["fill_time"])
        if side == "buy":
            if qty == 0:
                qty, weighted, entry_fee = q, price, fee
                entry_signal, entry_fill_time, entry_fill_price, buy_count = signal, fill_time, price, 1
            else:
                total = qty + q
                weighted = (weighted * qty + price * q) / total
                qty, entry_fee, buy_count = total, entry_fee + fee, buy_count + 1
            continue
        if side != "sell":
            raise ValueError(f"Unsupported fill side: {side}")
        if qty <= 0 or entry_signal is None or entry_fill_time is None:
            raise ValueError("Sell fill without open position")
        if abs(q - qty) > QTY_TOLERANCE:
            raise ValueError(f"Partial/oversized sell: sell={q} position={qty}")

        reason = str(signal.get("reason") or "UNKNOWN")
        exit_pnl = (price - weighted) * qty - entry_fee - fee
        group = _classify_exit(reason, exit_pnl)
        signal_time_raw = entry_signal.get("timestamp")
        if signal_time_raw is None:
            raise ValueError("Entry signal has no timestamp")
        signal_time = _utc(signal_time_raw)
        idx = by_time.get(signal_time)
        if idx is None:
            raise ValueError(f"Entry signal candle not found: {signal_time}")
        candle = candle_rows[idx]
        close = _d(candle.get("close_price"))
        if close is None:
            raise ValueError("Entry candle has no close_price")

        age, cursor = 0, idx
        while cursor >= 0 and str(candle_rows[cursor].get("regime") or "") == "TREND_UP":
            age, cursor = age + 1, cursor - 1
        age_censored = cursor < 0
        exit_signal_time_raw = signal.get("timestamp")
        exit_signal_time = _utc(exit_signal_time_raw) if exit_signal_time_raw else fill_time
        first_td: datetime | None = None
        for future in candle_rows[idx + 1:]:
            ts = _utc(future["open_time"])
            if ts > exit_signal_time:
                break
            if str(future.get("regime") or "") == "TREND_DOWN":
                first_td = ts
                break
        td_hours = None if first_td is None else Decimal(str((first_td - signal_time).total_seconds())) / Decimal("3600")

        ema20, ema50, ema200, atr = _d(candle.get("ema_20")), _d(candle.get("ema_50")), _d(candle.get("ema_200")), _d(candle.get("atr"))
        records.append(EntryQualityRecord(
            run_id=run_id, symbol=symbol, outcome_group=group, exit_reason=reason,
            entry_signal_time=signal_time, entry_fill_time=entry_fill_time,
            entry_signal_price=_d(entry_signal.get("price")) or close, entry_fill_price=entry_fill_price,
            weighted_entry_price=weighted, dca_count=max(0, buy_count - 1), rsi=_d(candle.get("rsi")),
            ema_20=ema20, ema_50=ema50, ema_200=ema200,
            close_to_ema20=_ratio(close, ema20), close_to_ema50=_ratio(close, ema50), close_to_ema200=_ratio(close, ema200),
            ema20_slope_10=_slope(candle_rows, idx, "ema_20"), ema50_slope_10=_slope(candle_rows, idx, "ema_50"), ema200_slope_10=_slope(candle_rows, idx, "ema_200"),
            atr=atr, atr_pct=(atr / close if atr is not None and close != 0 else None),
            volatility=_d(candle.get("volatility")), regime_confidence=_d(candle.get("regime_confidence")),
            trend_up_age_bars=age, trend_up_age_censored=age_censored,
            time_to_trend_down_hours=td_hours, trend_down_before_exit=first_td is not None,
            exit_time=fill_time, realized_pnl=exit_pnl,
        ))
        qty, weighted, entry_fee = Decimal("0"), Decimal("0"), Decimal("0")
        entry_signal, entry_fill_time, entry_fill_price, buy_count = None, None, Decimal("0"), 0
    return records


def summarize_group(group: str, records: list[EntryQualityRecord]) -> EntryQualityGroupSummary:
    selected = [r for r in records if r.outcome_group == group]
    ages = [Decimal(r.trend_up_age_bars) for r in selected]
    return EntryQualityGroupSummary(
        group=group, trades=len(selected), average_pnl=_avg([r.realized_pnl for r in selected]) or Decimal("0"),
        average_rsi=_avg([r.rsi for r in selected]), median_rsi=_median([r.rsi for r in selected]),
        average_close_to_ema20=_avg([r.close_to_ema20 for r in selected]), average_close_to_ema50=_avg([r.close_to_ema50 for r in selected]), average_close_to_ema200=_avg([r.close_to_ema200 for r in selected]),
        average_ema20_slope_10=_avg([r.ema20_slope_10 for r in selected]), average_ema50_slope_10=_avg([r.ema50_slope_10 for r in selected]), average_ema200_slope_10=_avg([r.ema200_slope_10 for r in selected]),
        average_atr_pct=_avg([r.atr_pct for r in selected]), average_volatility=_avg([r.volatility for r in selected]), average_regime_confidence=_avg([r.regime_confidence for r in selected]),
        average_trend_up_age_bars=_avg(ages) or Decimal("0"), median_trend_up_age_bars=_median(ages) or Decimal("0"),
        trend_down_before_exit=sum(r.trend_down_before_exit for r in selected),
        average_time_to_trend_down_hours=_avg([r.time_to_trend_down_hours for r in selected]),
    )


async def build_entry_quality_diagnostics(run_id: UUID, session_factory: async_sessionmaker[AsyncSession] = async_session_factory) -> EntryQualityReport:
    async with session_factory() as session:
        result = await session.execute(text("""
            SELECT run_id, exchange_name, symbol, interval_code, period_start, period_end,
                   indicator_model_version, regime_model_version
            FROM mart.backtest_run
            WHERE run_id=:run_id
        """), {"run_id": run_id})
        run = result.mappings().one_or_none()
        if run is None:
            raise ValueError(f"Backtest run not found: {run_id}")
        if str(run["interval_code"]) != "1h":
            raise ValueError("ENTRY QUALITY diagnostics currently supports only 1h runs")
        fills = await session.execute(text("""
            SELECT f.sequence_no, f.side, f.quantity, f.price, f.commission, f.fill_time, o.payload -> 'signal' AS signal
            FROM mart.backtest_fill f JOIN mart.backtest_order o ON o.run_id=f.run_id AND o.order_id=f.order_id
            WHERE f.run_id=:run_id ORDER BY f.sequence_no
        """), {"run_id": run_id})
        fill_rows = [dict(r) for r in fills.mappings().all()]
        candles = await session.execute(text("""
            SELECT c.open_time, c.close_price,
                   e20.indicator_value AS ema_20, e50.indicator_value AS ema_50, e200.indicator_value AS ema_200,
                   rsi.indicator_value AS rsi, atr.indicator_value AS atr, vol.indicator_value AS volatility,
                   mr.regime, mr.confidence AS regime_confidence
            FROM dds.candle c JOIN dds.instrument i ON i.instrument_id=c.instrument_id
            LEFT JOIN dds.indicator e20 ON e20.candle_id=c.candle_id AND e20.indicator_name='EMA' AND e20.indicator_params='{"period": 20}'::jsonb AND e20.model_version=:indicator_model_version
            LEFT JOIN dds.indicator e50 ON e50.candle_id=c.candle_id AND e50.indicator_name='EMA' AND e50.indicator_params='{"period": 50}'::jsonb AND e50.model_version=:indicator_model_version
            LEFT JOIN dds.indicator e200 ON e200.candle_id=c.candle_id AND e200.indicator_name='EMA' AND e200.indicator_params='{"period": 200}'::jsonb AND e200.model_version=:indicator_model_version
            LEFT JOIN dds.indicator rsi ON rsi.candle_id=c.candle_id AND rsi.indicator_name='RSI' AND rsi.indicator_params='{"period": 14}'::jsonb AND rsi.model_version=:indicator_model_version
            LEFT JOIN dds.indicator atr ON atr.candle_id=c.candle_id AND atr.indicator_name='ATR' AND atr.indicator_params='{"period": 14}'::jsonb AND atr.model_version=:indicator_model_version
            LEFT JOIN dds.indicator vol ON vol.candle_id=c.candle_id AND vol.indicator_name='VOLATILITY' AND vol.indicator_params='{"period": 20}'::jsonb AND vol.model_version=:indicator_model_version
            LEFT JOIN dds.market_regime mr ON mr.candle_id=c.candle_id AND mr.regime_model_version=:regime_model_version
            WHERE i.exchange_name=:exchange AND i.symbol=:symbol AND c.interval_code=:interval
              AND c.open_time>=:start AND c.open_time<:end AND c.is_valid=true ORDER BY c.open_time
        """), {
            "exchange": run["exchange_name"],
            "symbol": run["symbol"],
            "interval": run["interval_code"],
            "start": run["period_start"],
            "end": run["period_end"],
            "indicator_model_version": run["indicator_model_version"],
            "regime_model_version": run["regime_model_version"],
        })
        candle_rows = [dict(r) for r in candles.mappings().all()]
    records = reconstruct_entry_quality(run_id=run_id, symbol=str(run["symbol"]), fill_rows=fill_rows, candle_rows=candle_rows)
    return EntryQualityReport(
        run_id=run_id, symbol=str(run["symbol"]), interval=str(run["interval_code"]), records=tuple(records),
        trend_down_losses=summarize_group("TREND_DOWN_LOSS", records), winners=summarize_group("WINNER", records),
        other_trades=sum(r.outcome_group == "OTHER" for r in records),
    )
