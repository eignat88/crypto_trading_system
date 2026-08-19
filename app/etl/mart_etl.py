from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.reporting.paper_metrics import PaperMetricsCollector
from app.reporting.paper_pnl import PaperPnLTracker


@dataclass(frozen=True)
class MartLoadResult:
    daily: int = 0
    trades: int = 0
    drawdowns: int = 0
    monthly: int = 0


class MartETL:
    """Idempotently materialize restored paper-reporting state."""

    def __init__(self, session: AsyncSession, pnl_tracker: PaperPnLTracker,
                 metrics_collector: PaperMetricsCollector, exchange_name: str = "bybit") -> None:
        self.session = session
        self.tracker = pnl_tracker
        self.collector = metrics_collector
        self.exchange_name = exchange_name

    async def load(self) -> MartLoadResult:
        records_by_day: dict[date, list] = defaultdict(list)
        for record in self.tracker.pnl_records:
            records_by_day[record.timestamp.date()].append(record)
        trades_by_day: dict[date, list] = defaultdict(list)
        for trade in self.collector._trade_events:
            trades_by_day[trade["timestamp"].date()].append(trade)

        for report_date, records in records_by_day.items():
            first, last = records[0], records[-1]
            daily_pnl = last.equity - first.equity
            daily_pct = daily_pnl / first.equity * 100 if first.equity else Decimal("0")
            day_trades = trades_by_day.get(report_date, [])
            await self.session.execute(text("""
                INSERT INTO mart.daily_performance
                (report_date, exchange_name, total_capital, daily_pnl, daily_pnl_pct,
                 realized_pnl, unrealized_pnl, total_commission, trades_count,
                 max_drawdown, current_drawdown)
                VALUES (:day, :exchange, :equity, :pnl, :pct, :realized, :unrealized,
                        :fees, :trades, :max_dd, :current_dd)
                ON CONFLICT (report_date, exchange_name) DO UPDATE SET
                 total_capital=EXCLUDED.total_capital, daily_pnl=EXCLUDED.daily_pnl,
                 daily_pnl_pct=EXCLUDED.daily_pnl_pct, realized_pnl=EXCLUDED.realized_pnl,
                 unrealized_pnl=EXCLUDED.unrealized_pnl,
                 total_commission=EXCLUDED.total_commission, trades_count=EXCLUDED.trades_count,
                 max_drawdown=EXCLUDED.max_drawdown, current_drawdown=EXCLUDED.current_drawdown
            """), {"day": report_date, "exchange": self.exchange_name, "equity": last.equity,
                    "pnl": daily_pnl, "pct": daily_pct, "realized": last.realized_pnl,
                    "unrealized": last.unrealized_pnl, "fees": last.fees_paid,
                    "trades": len(day_trades),
                    "max_dd": max(p.drawdown_pct for p in self.tracker.equity_curve
                                  if p.timestamp.date() == report_date),
                    "current_dd": next(p.drawdown_pct for p in reversed(self.tracker.equity_curve)
                                       if p.timestamp.date() == report_date)})

        for report_date, trades in trades_by_day.items():
            volume = sum((t["quantity"] * t["price"] for t in trades), Decimal("0"))
            fees = sum((t["fee"] for t in trades), Decimal("0"))
            slippage = sum((t["slippage"] for t in trades), Decimal("0"))
            await self.session.execute(text("""
                INSERT INTO mart.trade_statistics
                (report_date, exchange_name, total_trades, total_volume, avg_trade_size,
                 total_commission, total_slippage)
                VALUES (:day,:exchange,:count,:volume,:average,:fees,:slippage)
                ON CONFLICT (report_date, exchange_name) DO UPDATE SET
                 total_trades=EXCLUDED.total_trades, total_volume=EXCLUDED.total_volume,
                 avg_trade_size=EXCLUDED.avg_trade_size,
                 total_commission=EXCLUDED.total_commission,
                 total_slippage=EXCLUDED.total_slippage
            """), {"day": report_date, "exchange": self.exchange_name, "count": len(trades),
                    "volume": volume, "average": volume / len(trades), "fees": fees,
                    "slippage": slippage})

        # The table predates exchange scoping; timestamp is the stable snapshot identity.
        for point in self.tracker.equity_curve:
            await self.session.execute(text("DELETE FROM mart.drawdown_history WHERE timestamp=:ts"),
                                       {"ts": point.timestamp})
            await self.session.execute(text("""
                INSERT INTO mart.drawdown_history
                (timestamp, equity, peak_equity, drawdown, drawdown_pct)
                VALUES (:ts,:equity,:peak,:drawdown,:pct)
            """), {"ts": point.timestamp, "equity": point.equity,
                    "peak": point.equity + point.drawdown, "drawdown": point.drawdown,
                    "pct": point.drawdown_pct})

        months = {record.timestamp.strftime("%Y-%m") for record in self.tracker.pnl_records}
        for month in months:
            records = [r for r in self.tracker.pnl_records if r.timestamp.strftime("%Y-%m") == month]
            month_trades = [t for t in self.collector._trade_events
                            if t["timestamp"].strftime("%Y-%m") == month]
            pnl = records[-1].equity - records[0].equity
            pct = pnl / records[0].equity * 100 if records[0].equity else Decimal("0")
            points = [p for p in self.tracker.equity_curve if p.timestamp.strftime("%Y-%m") == month]
            await self.session.execute(text("""
                INSERT INTO mart.monthly_returns
                (year_month, exchange_name, total_pnl, total_pnl_pct, trades_count, max_drawdown)
                VALUES (:month,:exchange,:pnl,:pct,:trades,:drawdown)
                ON CONFLICT (year_month, exchange_name) DO UPDATE SET
                 total_pnl=EXCLUDED.total_pnl, total_pnl_pct=EXCLUDED.total_pnl_pct,
                 trades_count=EXCLUDED.trades_count, max_drawdown=EXCLUDED.max_drawdown
            """), {"month": month, "exchange": self.exchange_name, "pnl": pnl, "pct": pct,
                    "trades": len(month_trades), "drawdown": max(p.drawdown_pct for p in points)})
        await self.session.commit()
        return MartLoadResult(len(records_by_day), len(trades_by_day),
                              len(self.tracker.equity_curve), len(months))
