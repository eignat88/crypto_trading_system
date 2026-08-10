from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.reporting.trend_down_diagnostics_query import build_trend_down_diagnostics


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _pct(count: int, total: int) -> Decimal:
    return Decimal(count) / Decimal(total) if total else Decimal("0")


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose baseline TrendDCA exits caused by TREND_DOWN"
    )
    parser.add_argument("--run-id", action="append", required=True)
    args = parser.parse_args()

    reports = []
    for raw_run_id in args.run_id:
        report = await build_trend_down_diagnostics(UUID(raw_run_id))
        reports.append(report)

        print()
        print(f"TREND_DOWN DIAGNOSTICS: {report.symbol}")
        print("=" * (24 + len(report.symbol)))
        print(f"run_id                         : {report.run_id}")
        print(f"interval                       : {report.interval}")
        print(f"trend_down_exits               : {report.total_exits}")
        print(f"continued_3_bars               : {report.continued_3_bars}")
        print(f"continued_3_bar_rate           : {report.continued_3_bar_rate}")
        print(f"false_switches_within_3_bars   : {report.false_switches_within_3_bars}")
        print(f"false_switch_rate              : {report.false_switch_rate}")
        print(f"price_lower_after_1_bar        : {report.price_lower_after_1_bar}")
        print(f"price_lower_after_2_bars       : {report.price_lower_after_2_bars}")
        print(f"price_lower_after_3_bars       : {report.price_lower_after_3_bars}")
        print(f"avg_pnl_at_first_trend_down    : {report.average_pnl_at_first_trend_down}")
        print(f"avg_actual_realized_pnl        : {report.average_actual_pnl}")
        print()
        print("TRADES")
        print("------")
        for index, item in enumerate(report.records, start=1):
            print(
                f"{index:02d} entry={item.entry_time.isoformat()} "
                f"dca={item.dca_count} weighted={item.weighted_entry_price} "
                f"td={item.first_trend_down_time.isoformat()} "
                f"td_price={item.first_trend_down_price} "
                f"r1={_fmt(item.close_return_1_bar)} "
                f"r2={_fmt(item.close_return_2_bars)} "
                f"r3={_fmt(item.close_return_3_bars)} "
                f"regimes={item.regime_after_1_bar}/{item.regime_after_2_bars}/{item.regime_after_3_bars} "
                f"continued3={item.trend_down_continued_3_bars} "
                f"false_switch={item.false_switch_within_3_bars} "
                f"actual_pnl={item.actual_realized_pnl}"
            )

    total = sum(report.total_exits for report in reports)
    continued = sum(report.continued_3_bars for report in reports)
    false_switches = sum(report.false_switches_within_3_bars for report in reports)
    lower_1 = sum(report.price_lower_after_1_bar for report in reports)
    lower_2 = sum(report.price_lower_after_2_bars for report in reports)
    lower_3 = sum(report.price_lower_after_3_bars for report in reports)

    print()
    print("COMBINED TREND_DOWN SUMMARY")
    print("===========================")
    print(f"symbols                        : {','.join(report.symbol for report in reports)}")
    print(f"trend_down_exits               : {total}")
    print(f"continued_3_bars               : {continued}")
    print(f"continued_3_bar_rate           : {_pct(continued, total)}")
    print(f"false_switches_within_3_bars   : {false_switches}")
    print(f"false_switch_rate              : {_pct(false_switches, total)}")
    print(f"price_lower_after_1_bar        : {lower_1}/{total} ({_pct(lower_1, total)})")
    print(f"price_lower_after_2_bars       : {lower_2}/{total} ({_pct(lower_2, total)})")
    print(f"price_lower_after_3_bars       : {lower_3}/{total} ({_pct(lower_3, total)})")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"trend_down_exit_diagnostics_{timestamp}"
    json_file = output_dir / f"{stem}.json"
    csv_file = output_dir / f"{stem}.csv"

    payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc),
            "definition": {
                "first_trend_down": "baseline CLOSE signal candle with reason Regime changed to TREND_DOWN",
                "future_prices": "close of +1/+2/+3 1h candles after signal candle",
                "future_extremes": "minimum low and maximum high across +1/+2/+3 candles",
                "pnl_at_first_trend_down": "hypothetical immediate close at signal close with taker commission, no next-open slippage",
                "false_switch_within_3_bars": "at least one of +1/+2/+3 regimes is not TREND_DOWN",
            },
        },
        "summary": {
            "symbols": [report.symbol for report in reports],
            "trend_down_exits": total,
            "continued_3_bars": continued,
            "continued_3_bar_rate": _pct(continued, total),
            "false_switches_within_3_bars": false_switches,
            "false_switch_rate": _pct(false_switches, total),
            "price_lower_after_1_bar": lower_1,
            "price_lower_after_2_bars": lower_2,
            "price_lower_after_3_bars": lower_3,
        },
        "reports": [asdict(report) for report in reports],
    }
    json_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    fieldnames = [
        "run_id", "symbol", "entry_time", "entry_price", "dca_count",
        "weighted_entry_price", "quantity", "first_trend_down_time",
        "first_trend_down_price", "pnl_at_first_trend_down",
        "price_after_1_bar", "price_after_2_bars", "price_after_3_bars",
        "regime_after_1_bar", "regime_after_2_bars", "regime_after_3_bars",
        "min_low_next_3_bars", "max_high_next_3_bars",
        "close_return_1_bar", "close_return_2_bars", "close_return_3_bars",
        "min_low_return_next_3_bars", "max_high_return_next_3_bars",
        "trend_down_continued_3_bars", "false_switch_within_3_bars",
        "actual_exit_time", "actual_exit_price", "actual_realized_pnl",
    ]
    with csv_file.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for report in reports:
            for record in report.records:
                writer.writerow(
                    {key: _json_default(value) for key, value in asdict(record).items()}
                )

    print(f"json_artifact                  : {json_file}")
    print(f"csv_artifact                   : {csv_file}")


if __name__ == "__main__":
    asyncio.run(main())
