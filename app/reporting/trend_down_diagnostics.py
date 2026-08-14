from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.backtest.commission_model import CommissionConfig, CommissionModel
from app.database.connection import async_session_factory

TREND_DOWN_EXIT_REASON = "Regime changed to TREND_DOWN"
_QUANTITY_TOLERANCE = Decimal("1E-17")


@dataclass(frozen=True)
class TrendDownDiagnostic:
    run_id: UUID
    symbol: str
    entry_time: datetime
    entry_price: Decimal
    dca_count: int
    weighted_entry_price: Decimal
    quantity: Decimal
    first_trend_down_time: datetime
    first_trend_down_price: Decimal
    pnl_at_first_trend_down: Decimal
    price_after_1_bar: Decimal | None
    price_after_2_bars: Decimal | None
    price_after_3_bars: Decimal | None
    regime_after_1_bar: str | None
    regime_after_2_bars: str | None
    regime_after_3_bars: str | None
    min_low_next_3_bars: Decimal | None
    max_high_next_3_bars: Decimal | None
    close_return_1_bar: Decimal | None
    close_return_2_bars: Decimal | None
    close_return_3_bars: Decimal | None
    min_low_return_next_3_bars: Decimal | None
    max_high_return_next_3_bars: Decimal | None
    trend_down_continued_3_bars: bool
    false_switch_within_3_bars: bool
    actual_exit_time: datetime
    actual_exit_price: Decimal
    actual_realized_pnl: Decimal


@dataclass(frozen=True)
class TrendDownDiagnosticsReport:
    run_id: UUID
    symbol: str
    interval: str
    records: tuple[TrendDownDiagnostic, ...]
    total_exits: int
    continued_3_bars: int
    false_switches_within_3_bars: int
    price_lower_after_1_bar: int
    price_lower_after_2_bars: int
    price_lower_after_3_bars: int
    average_actual_pnl: Decimal
    average_pnl_at_first_trend_down: Decimal

    @property
    def continued_3_bar_rate(self) -> Decimal:
        return (
            Decimal(self.continued_3_bars) / Decimal(self.total_exits)
            if self.total_exits
            else Decimal("0")
        )

    @property
    def false_switch_rate(self) -> Decimal:
        return (
            Decimal(self.false_switches_within_3_bars) / Decimal(self.total_exits)
            if self.total_exits
            else Decimal("0")
        )


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _utc(value: datetime | str) -> datetime:
    if isinstance(value, str):
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
    else:
        parsed = value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _signal(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("signal") or {}
    if isinstance(value, str):
        return json.loads(value)
    return dict(value)


def _return_from(reference: Decimal, value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return (value - reference) / reference


def reconstruct_trend_down_exits(
    *,
    run_id: UUID,
    symbol: str,
    fill_rows: list[dict[str, Any]],
    candle_rows: list[dict[str, Any]],
    commission_config: CommissionConfig,
    bar_delta: timedelta = timedelta(hours=1),
) -> list[TrendDownDiagnostic]:
    """Reconstruct baseline TREND_DOWN exits and inspect the next three candles.

    ``pnl_at_first_trend_down`` is a diagnostic hypothetical immediate-close PnL
    at the signal candle close, using the same taker commission model but no
    next-open slippage. It is not a counterfactual backtest result.
    """
    candle_by_time = {_utc(row["open_time"]): row for row in candle_rows}
    commission_model = CommissionModel(commission_config)

    position_quantity = Decimal("0")
    weighted_entry_price = Decimal("0")
    entry_commission = Decimal("0")
    entry_time: datetime | None = None
    first_entry_price = Decimal("0")
    buy_count = 0
    records: list[TrendDownDiagnostic] = []

    for row in fill_rows:
        side = str(row["side"]).lower()
        quantity = _decimal(row["quantity"])
        price = _decimal(row["price"])
        commission = _decimal(row["commission"])
        fill_time = _utc(row["fill_time"])
        signal = _signal(row)

        if side == "buy":
            if position_quantity == 0:
                position_quantity = quantity
                weighted_entry_price = price
                entry_commission = commission
                entry_time = fill_time
                first_entry_price = price
                buy_count = 1
            else:
                total_quantity = position_quantity + quantity
                weighted_entry_price = (
                    weighted_entry_price * position_quantity + price * quantity
                ) / total_quantity
                position_quantity = total_quantity
                entry_commission += commission
                buy_count += 1
            continue

        if side != "sell":
            raise ValueError(f"Unsupported fill side: {side}")
        if position_quantity <= 0 or entry_time is None:
            raise ValueError("Sell fill without an open position in audit")
        if abs(quantity - position_quantity) > _QUANTITY_TOLERANCE:
            raise ValueError(
                "Partial/oversized sell is not supported by TREND_DOWN diagnostics: "
                f"sell={quantity} position={position_quantity}"
            )

        reason = str(signal.get("reason") or "")
        actual_pnl = (
            (price - weighted_entry_price) * position_quantity
            - entry_commission
            - commission
        )

        if reason == TREND_DOWN_EXIT_REASON:
            signal_time_raw = signal.get("timestamp")
            if signal_time_raw is None:
                raise ValueError("TREND_DOWN exit signal has no timestamp")
            signal_time = _utc(signal_time_raw)
            signal_price = _decimal(signal.get("price"))

            hypothetical_exit_commission = commission_model.calculate_commission(
                position_quantity,
                signal_price,
                is_maker=False,
            )
            pnl_at_signal = (
                (signal_price - weighted_entry_price) * position_quantity
                - entry_commission
                - hypothetical_exit_commission
            )

            future = [
                candle_by_time.get(signal_time + bar_delta * offset)
                for offset in (1, 2, 3)
            ]
            closes = [
                None if item is None else _decimal(item["close_price"])
                for item in future
            ]
            regimes = [
                None if item is None else str(item.get("regime") or "UNKNOWN")
                for item in future
            ]
            lows = [
                _decimal(item["low_price"])
                for item in future
                if item is not None
            ]
            highs = [
                _decimal(item["high_price"])
                for item in future
                if item is not None
            ]

            continued = all(regime == "TREND_DOWN" for regime in regimes)
            false_switch = any(
                regime not in (None, "TREND_DOWN") for regime in regimes
            )
            min_low = min(lows) if lows else None
            max_high = max(highs) if highs else None

            records.append(
                TrendDownDiagnostic(
                    run_id=run_id,
                    symbol=symbol,
                    entry_time=entry_time,
                    entry_price=first_entry_price,
                    dca_count=max(buy_count - 1, 0),
                    weighted_entry_price=weighted_entry_price,
                    quantity=position_quantity,
                    first_trend_down_time=signal_time,
                    first_trend_down_price=signal_price,
                    pnl_at_first_trend_down=pnl_at_signal,
                    price_after_1_bar=closes[0],
                    price_after_2_bars=closes[1],
                    price_after_3_bars=closes[2],
                    regime_after_1_bar=regimes[0],
                    regime_after_2_bars=regimes[1],
                    regime_after_3_bars=regimes[2],
                    min_low_next_3_bars=min_low,
                    max_high_next_3_bars=max_high,
                    close_return_1_bar=_return_from(signal_price, closes[0]),
                    close_return_2_bars=_return_from(signal_price, closes[1]),
                    close_return_3_bars=_return_from(signal_price, closes[2]),
                    min_low_return_next_3_bars=_return_from(signal_price, min_low),
                    max_high_return_next_3_bars=_return_from(signal_price, max_high),
                    trend_down_continued_3_bars=continued,
                    false_switch_within_3_bars=false_switch,
                    actual_exit_time=fill_time,
                    actual_exit_price=price,
                    actual_realized_pnl=actual_pnl,
                )
            )

        position_quantity = Decimal("0")
        weighted_entry_price = Decimal("0")
        entry_commission = Decimal("0")
        entry_time = None
        first_entry_price = Decimal("0")
        buy_count = 0

    return records


def summarize_trend_down_diagnostics(
    *,
    run_id: UUID,
    symbol: str,
    interval: str,
    records: list[TrendDownDiagnostic],
) -> TrendDownDiagnosticsReport:
    total = len(records)
    return TrendDownDiagnosticsReport(
        run_id=run_id,
        symbol=symbol,
        interval=interval,
        records=tuple(records),
        total_exits=total,
        continued_3_bars=sum(item.trend_down_continued_3_bars for item in records),
        false_switches_within_3_bars=sum(
            item.false_switch_within_3_bars for item in records
        ),
        price_lower_after_1_bar=sum(
            item.close_return_1_bar is not None and item.close_return_1_bar < 0
            for item in records
        ),
        price_lower_after_2_bars=sum(
            item.close_return_2_bars is not None and item.close_return_2_bars < 0
            for item in records
        ),
        price_lower_after_3_bars=sum(
            item.close_return_3_bars is not None and item.close_return_3_bars < 0
            for item in records
        ),
        average_actual_pnl=(
            sum((item.actual_realized_pnl for item in records), Decimal("0"))
            / Decimal(total)
            if total
            else Decimal("0")
        ),
        average_pnl_at_first_trend_down=(
            sum((item.pnl_at_first_trend_down for item in records), Decimal("0"))
            / Decimal(total)
            if total
            else Decimal("0")
        ),
    )


async def build_trend_down_diagnostics(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
) -> TrendDownDiagnosticsReport:
    async with session_factory() as session:
        run_result = await session.execute(
            text(
                """
                SELECT run_id, exchange_name, symbol, interval_code,
                       period_start, period_end, backtest_config,
                       regime_model_version
                FROM mart.backtest_run
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        run = run_result.mappings().one_or_none()
        if run is None:
            raise ValueError(f"Backtest run not found: {run_id}")
        if str(run["interval_code"]) != "1h":
            raise ValueError(
                "TREND_DOWN diagnostics currently supports only 1h baseline runs"
            )

        fill_result = await session.execute(
            text(
                """
                SELECT f.sequence_no, f.side, f.quantity, f.price, f.commission,
                       f.fill_time, o.payload -> 'signal' AS signal
                FROM mart.backtest_fill f
                JOIN mart.backtest_order o
                  ON o.run_id = f.run_id
                 AND o.order_id = f.order_id
                WHERE f.run_id = :run_id
                ORDER BY f.sequence_no
                """
            ),
            {"run_id": run_id},
        )
        fill_rows = [dict(row) for row in fill_result.mappings().all()]

        candle_result = await session.execute(
            text(
                """
                SELECT c.open_time, c.close_price, c.low_price, c.high_price,
                       mr.regime
                FROM dds.candle c
                JOIN dds.instrument i ON i.instrument_id = c.instrument_id
                LEFT JOIN dds.market_regime mr
                  ON mr.candle_id = c.candle_id
                 AND mr.regime_model_version = :regime_model_version
                WHERE i.exchange_name = :exchange_name
                  AND i.symbol = :symbol
                  AND c.interval_code = :interval_code
                  AND c.open_time >= :period_start
                  AND c.open_time < :period_end + interval '4 hours'
                  AND c.is_valid = true
                ORDER BY c.open_time
                """
            ),
            {
                "exchange_name": run["exchange_name"],
                "symbol": run["symbol"],
                "interval_code": run["interval_code"],
                "period_start": run["period_start"],
                "period_end": run["period_end"],
                "regime_model_version": run["regime_model_version"],
            },
        )
        candle_rows = [dict(row) for row in candle_result.mappings().all()]

    config = run["backtest_config"] or {}
    if isinstance(config, str):
        config = json.loads(config)
    commission = config.get("commission", {})
    commission_config = CommissionConfig(
        maker_fee=_decimal(commission.get("maker_fee", "0.001")),
        taker_fee=_decimal(commission.get("taker_fee", "0.001")),
        minimum_fee=_decimal(commission.get("minimum_fee", "0.0001")),
    )

    records = reconstruct_trend_down_exits(
        run_id=run_id,
        symbol=str(run["symbol"]),
        fill_rows=fill_rows,
        candle_rows=candle_rows,
        commission_config=commission_config,
        bar_delta=timedelta(hours=1),
    )
    return summarize_trend_down_diagnostics(
        run_id=run_id,
        symbol=str(run["symbol"]),
        interval=str(run["interval_code"]),
        records=records,
    )
