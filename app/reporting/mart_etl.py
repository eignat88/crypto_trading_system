"""Idempotent paper-trading aggregates for the first MART reporting slice."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.reporting.paper_metrics import PaperMetricsCollector
from app.reporting.paper_pnl import EquityPoint, PaperPnLTracker, PnLRecord

ZERO = Decimal("0")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class MartLoadResult:
    """Number of source aggregates offered to each MART upsert."""

    daily_performance: int
    trade_statistics: int
    drawdown_history: int
    monthly_returns: int


class MartETL:
    """Build MART rows from the live paper reporting state and DDS positions.

    The SQL writes deliberately update every mutable measure on conflict. Replaying
    the same tracker/collector state therefore repairs rows instead of duplicating
    them. The supplied session controls the transaction boundary.
    """

    def __init__(
        self,
        session: AsyncSession,
        pnl_tracker: PaperPnLTracker,
        metrics_collector: PaperMetricsCollector,
        exchange_name: str = "bybit",
    ) -> None:
        if not exchange_name.strip():
            raise ValueError("exchange_name must not be empty")
        self._session = session
        self._tracker = pnl_tracker
        self._collector = metrics_collector
        self._exchange_name = exchange_name

    async def load(self) -> MartLoadResult:
        """Calculate and upsert the four phase-one MART datasets."""
        records = sorted(self._tracker.pnl_records, key=lambda row: row.timestamp)
        curve = sorted(self._tracker.equity_curve, key=lambda row: row.timestamp)
        trades = sorted(self._collector.trade_events, key=lambda row: row["timestamp"])

        open_positions = await self._open_positions()
        daily = self._daily_rows(records, curve, trades, open_positions)
        trade_stats = self._trade_stat_rows(trades)
        monthly = self._monthly_rows(daily)

        for row in daily:
            await self._session.execute(text(_UPSERT_DAILY), row)
        for row in trade_stats:
            await self._session.execute(text(_UPSERT_TRADE_STATS), row)
        for point in curve:
            await self._session.execute(text(_UPSERT_DRAWDOWN), self._drawdown_row(point))
        for row in monthly:
            await self._session.execute(text(_UPSERT_MONTHLY), row)

        return MartLoadResult(len(daily), len(trade_stats), len(curve), len(monthly))

    async def _open_positions(self) -> int:
        result = await self._session.execute(
            text("SELECT count(*) FROM dds.paper_positions WHERE quantity <> 0")
        )
        return int(result.scalar_one())

    def _daily_rows(
        self,
        records: Sequence[PnLRecord],
        curve: Sequence[EquityPoint],
        trades: Sequence[Mapping[str, Any]],
        open_positions: int,
    ) -> list[dict[str, Any]]:
        records_by_day: dict[date, list[PnLRecord]] = defaultdict(list)
        curve_by_day: dict[date, list[EquityPoint]] = defaultdict(list)
        trades_by_day: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
        for row in records:
            records_by_day[row.timestamp.date()].append(row)
        for point in curve:
            curve_by_day[point.timestamp.date()].append(point)
        for trade in trades:
            trades_by_day[trade["timestamp"].date()].append(trade)

        rows: list[dict[str, Any]] = []
        previous_equity = self._tracker.initial_capital
        previous_realized = previous_fees = ZERO
        realized_trades = self._realized_trade_pnl(trades)
        realized_by_day: dict[date, list[Decimal]] = defaultdict(list)
        for timestamp, pnl in realized_trades:
            realized_by_day[timestamp.date()].append(pnl)

        for report_date in sorted(records_by_day):
            final = records_by_day[report_date][-1]
            day_curve = curve_by_day[report_date]
            day_trades = trades_by_day[report_date]
            pnl = final.equity - previous_equity
            denominator = previous_equity
            rows.append(
                {
                    "report_date": report_date,
                    "exchange_name": self._exchange_name,
                    "total_capital": final.equity,
                    "daily_pnl": pnl,
                    "daily_pnl_pct": self._pct(pnl, denominator),
                    "realized_pnl": final.realized_pnl - previous_realized,
                    "unrealized_pnl": final.unrealized_pnl,
                    "total_commission": final.fees_paid - previous_fees,
                    "trades_count": len(day_trades),
                    "winning_trades": sum(value > ZERO for value in realized_by_day[report_date]),
                    "losing_trades": sum(value < ZERO for value in realized_by_day[report_date]),
                    "max_drawdown": max((point.drawdown_pct for point in day_curve), default=ZERO),
                    "current_drawdown": day_curve[-1].drawdown_pct if day_curve else ZERO,
                    "open_positions": open_positions
                    if report_date == records[-1].timestamp.date()
                    else 0,
                    "capital_utilization": self._pct(final.position_value, final.equity),
                }
            )
            previous_equity = final.equity
            previous_realized = final.realized_pnl
            previous_fees = final.fees_paid
        return rows

    def _trade_stat_rows(self, trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[date, list[Mapping[str, Any]]] = defaultdict(list)
        for trade in trades:
            grouped[trade["timestamp"].date()].append(trade)
        rows = []
        for report_date in sorted(grouped):
            day_trades = grouped[report_date]
            volumes = [Decimal(str(t["quantity"])) * Decimal(str(t["price"])) for t in day_trades]
            rows.append(
                {
                    "report_date": report_date,
                    "exchange_name": self._exchange_name,
                    "total_trades": len(day_trades),
                    "total_volume": sum(volumes, ZERO),
                    "avg_trade_size": sum(volumes, ZERO) / len(volumes),
                    "total_commission": sum(
                        (Decimal(str(t.get("fee", ZERO))) for t in day_trades), ZERO
                    ),
                    "total_slippage": sum(
                        (Decimal(str(t.get("slippage", ZERO))) for t in day_trades), ZERO
                    ),
                }
            )
        return rows

    def _monthly_rows(self, daily: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in daily:
            grouped[row["report_date"].strftime("%Y-%m")].append(row)
        rows = []
        for year_month in sorted(grouped):
            days = grouped[year_month]
            total_pnl = sum((Decimal(row["daily_pnl"]) for row in days), ZERO)
            starting_equity = Decimal(days[0]["total_capital"]) - Decimal(days[0]["daily_pnl"])
            wins = sum(int(row["winning_trades"]) for row in days)
            losses = sum(int(row["losing_trades"]) for row in days)
            closed = wins + losses
            rows.append(
                {
                    "year_month": year_month,
                    "exchange_name": self._exchange_name,
                    "total_pnl": total_pnl,
                    "total_pnl_pct": self._pct(total_pnl, starting_equity),
                    "trades_count": sum(int(row["trades_count"]) for row in days),
                    "win_rate": Decimal(wins) / Decimal(closed) if closed else ZERO,
                    "max_drawdown": max(Decimal(row["max_drawdown"]) for row in days),
                }
            )
        return rows

    def _drawdown_row(self, point: EquityPoint) -> dict[str, Any]:
        return {
            "timestamp": point.timestamp,
            "equity": point.equity,
            "peak_equity": point.equity + point.drawdown,
            "drawdown": point.drawdown,
            "drawdown_pct": point.drawdown_pct,
        }

    @staticmethod
    def _pct(value: Decimal, denominator: Decimal) -> Decimal:
        return value / denominator * HUNDRED if denominator else ZERO

    @staticmethod
    def _realized_trade_pnl(
        trades: Sequence[Mapping[str, Any]],
    ) -> list[tuple[datetime, Decimal]]:
        positions: dict[str, tuple[Decimal, Decimal]] = {}
        realized: list[tuple[datetime, Decimal]] = []
        for trade in trades:
            symbol = str(trade["symbol"])
            quantity = Decimal(str(trade["quantity"]))
            price = Decimal(str(trade["price"]))
            held, average = positions.get(symbol, (ZERO, ZERO))
            if str(trade["side"]).upper() == "BUY":
                new_held = held + quantity
                positions[symbol] = (new_held, (held * average + quantity * price) / new_held)
            elif str(trade["side"]).upper() == "SELL":
                if quantity > held:
                    raise ValueError(f"Sell quantity exceeds collected position for {symbol}")
                realized.append((trade["timestamp"], quantity * (price - average)))
                positions[symbol] = (held - quantity, average if held > quantity else ZERO)
            else:
                raise ValueError(f"Unsupported trade side: {trade['side']}")
        return realized


_UPSERT_DAILY = """
INSERT INTO mart.daily_performance (
 report_date, exchange_name, total_capital, daily_pnl, daily_pnl_pct, realized_pnl,
 unrealized_pnl, total_commission, trades_count, winning_trades, losing_trades,
 max_drawdown, current_drawdown, open_positions, capital_utilization)
VALUES (:report_date, :exchange_name, :total_capital, :daily_pnl, :daily_pnl_pct,
 :realized_pnl, :unrealized_pnl, :total_commission, :trades_count, :winning_trades,
 :losing_trades, :max_drawdown, :current_drawdown, :open_positions, :capital_utilization)
ON CONFLICT (report_date, exchange_name) DO UPDATE SET
 total_capital=EXCLUDED.total_capital, daily_pnl=EXCLUDED.daily_pnl,
 daily_pnl_pct=EXCLUDED.daily_pnl_pct, realized_pnl=EXCLUDED.realized_pnl,
 unrealized_pnl=EXCLUDED.unrealized_pnl, total_commission=EXCLUDED.total_commission,
 trades_count=EXCLUDED.trades_count, winning_trades=EXCLUDED.winning_trades,
 losing_trades=EXCLUDED.losing_trades, max_drawdown=EXCLUDED.max_drawdown,
 current_drawdown=EXCLUDED.current_drawdown, open_positions=EXCLUDED.open_positions,
 capital_utilization=EXCLUDED.capital_utilization
"""

_UPSERT_TRADE_STATS = """
INSERT INTO mart.trade_statistics (report_date, exchange_name, total_trades, total_volume,
 avg_trade_size, total_commission, total_slippage)
VALUES (:report_date, :exchange_name, :total_trades, :total_volume, :avg_trade_size,
 :total_commission, :total_slippage)
ON CONFLICT (report_date, exchange_name) DO UPDATE SET total_trades=EXCLUDED.total_trades,
 total_volume=EXCLUDED.total_volume, avg_trade_size=EXCLUDED.avg_trade_size,
 total_commission=EXCLUDED.total_commission, total_slippage=EXCLUDED.total_slippage
"""

_UPSERT_DRAWDOWN = """
INSERT INTO mart.drawdown_history (timestamp, equity, peak_equity, drawdown, drawdown_pct)
VALUES (:timestamp, :equity, :peak_equity, :drawdown, :drawdown_pct)
ON CONFLICT (timestamp) DO UPDATE SET equity=EXCLUDED.equity,
 peak_equity=EXCLUDED.peak_equity, drawdown=EXCLUDED.drawdown,
 drawdown_pct=EXCLUDED.drawdown_pct
"""

_UPSERT_MONTHLY = """
INSERT INTO mart.monthly_returns (year_month, exchange_name, total_pnl, total_pnl_pct,
 trades_count, win_rate, max_drawdown)
VALUES (:year_month, :exchange_name, :total_pnl, :total_pnl_pct, :trades_count,
 :win_rate, :max_drawdown)
ON CONFLICT (year_month, exchange_name) DO UPDATE SET total_pnl=EXCLUDED.total_pnl,
 total_pnl_pct=EXCLUDED.total_pnl_pct, trades_count=EXCLUDED.trades_count,
 win_rate=EXCLUDED.win_rate, max_drawdown=EXCLUDED.max_drawdown
"""
