from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
from uuid import UUID

from app.reporting.backtest_attribution import BacktestAttribution, build_backtest_attribution


def _format_decimal(value: Decimal) -> str:
    return format(value, "f")


def _print_buckets(title: str, buckets) -> None:
    print()
    print(title)
    print("-" * len(title))
    print(f"{'key':<28} {'trades':>7} {'wins':>6} {'losses':>7} {'win_rate':>12} {'pnl':>18} {'profit_factor':>15}")
    for bucket in buckets:
        pf = "Infinity" if bucket.profit_factor.is_infinite() else _format_decimal(bucket.profit_factor)
        print(
            f"{bucket.key:<28} {bucket.trades:>7} {bucket.wins:>6} {bucket.losses:>7} "
            f"{_format_decimal(bucket.win_rate):>12} {_format_decimal(bucket.pnl):>18} {pf:>15}"
        )


def print_report(report: BacktestAttribution) -> None:
    print()
    print("BACKTEST ATTRIBUTION")
    print("--------------------")
    print(f"run_id               : {report.run_id}")
    print(f"symbol               : {report.symbol}")
    print(f"trades               : {report.total_trades}")
    print(f"persisted_total_pnl  : {_format_decimal(report.total_pnl)}")
    print(f"attributed_total_pnl : {_format_decimal(report.attributed_pnl)}")
    print(f"reconciliation_delta : {_format_decimal(report.reconciliation_delta)}")

    _print_buckets("BY EXIT MONTH", report.by_month)
    _print_buckets("BY ENTRY MARKET REGIME", report.by_entry_regime)
    _print_buckets("BY EXIT REASON", report.by_exit_reason)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build read-only PnL attribution for persisted backtest runs"
    )
    parser.add_argument(
        "--run-id",
        action="append",
        required=True,
        help="Backtest run UUID. Repeat --run-id to report multiple runs.",
    )
    args = parser.parse_args()

    for raw_run_id in args.run_id:
        report = await build_backtest_attribution(UUID(raw_run_id))
        print_report(report)


if __name__ == "__main__":
    asyncio.run(main())
