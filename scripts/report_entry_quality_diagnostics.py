from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.reporting.entry_quality_diagnostics import build_entry_quality_diagnostics


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _fmt(value: Any) -> str:
    return "" if value is None else str(value)


def _print_group(label: str, group: Any) -> None:
    print(label)
    print("-" * len(label))
    print(f"trades                       : {group.trades}")
    print(f"average_pnl                  : {group.average_pnl}")
    print(f"average_rsi                  : {_fmt(group.average_rsi)}")
    print(f"median_rsi                   : {_fmt(group.median_rsi)}")
    print(f"avg_close_to_ema20           : {_fmt(group.average_close_to_ema20)}")
    print(f"avg_close_to_ema50           : {_fmt(group.average_close_to_ema50)}")
    print(f"avg_close_to_ema200          : {_fmt(group.average_close_to_ema200)}")
    print(f"avg_ema20_slope_10           : {_fmt(group.average_ema20_slope_10)}")
    print(f"avg_ema50_slope_10           : {_fmt(group.average_ema50_slope_10)}")
    print(f"avg_ema200_slope_10          : {_fmt(group.average_ema200_slope_10)}")
    print(f"avg_atr_pct                  : {_fmt(group.average_atr_pct)}")
    print(f"avg_volatility               : {_fmt(group.average_volatility)}")
    print(f"avg_regime_confidence        : {_fmt(group.average_regime_confidence)}")
    print(f"avg_trend_up_age_bars        : {group.average_trend_up_age_bars}")
    print(f"median_trend_up_age_bars     : {group.median_trend_up_age_bars}")
    print(f"trend_down_before_exit       : {group.trend_down_before_exit}")
    print(f"avg_time_to_trend_down_hours : {_fmt(group.average_time_to_trend_down_hours)}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare baseline TrendDCA entry quality for TREND_DOWN losses vs TP/trailing winners"
    )
    parser.add_argument("--run-id", action="append", required=True)
    args = parser.parse_args()

    reports = []
    for raw in args.run_id:
        report = await build_entry_quality_diagnostics(UUID(raw))
        reports.append(report)
        print()
        print(f"ENTRY QUALITY DIAGNOSTICS: {report.symbol}")
        print("=" * (27 + len(report.symbol)))
        print(f"run_id                       : {report.run_id}")
        print(f"interval                     : {report.interval}")
        print(f"all_reconstructed_trades     : {len(report.records)}")
        print(f"other_trades                 : {report.other_trades}")
        print()
        _print_group("TREND_DOWN_LOSS", report.trend_down_losses)
        print()
        _print_group("WINNER", report.winners)

    td = [r for report in reports for r in report.records if r.outcome_group == "TREND_DOWN_LOSS"]
    winners = [r for report in reports for r in report.records if r.outcome_group == "WINNER"]
    print()
    print("COMBINED ENTRY QUALITY SUMMARY")
    print("==============================")
    print(f"symbols                    : {','.join(r.symbol for r in reports)}")
    print(f"trend_down_losses          : {len(td)}")
    print(f"winners                    : {len(winners)}")
    print(f"other_trades               : {sum(r.other_trades for r in reports)}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    stem = f"entry_quality_diagnostics_{timestamp}"
    json_file = output_dir / f"{stem}.json"
    csv_file = output_dir / f"{stem}.csv"

    payload = {
        "metadata": {
            "created_at": datetime.now(UTC),
            "groups": {
                "TREND_DOWN_LOSS": "exit reason Regime changed to TREND_DOWN",
                "WINNER": "exit reason Take-profit hit / Take profit hit / Trailing stop hit",
                "OTHER": "all other exit reasons; excluded from primary comparison",
            },
            "definitions": {
                "entry_signal_time": "signal candle timestamp; indicators are read from this causal candle",
                "entry_fill_time": "actual next-bar execution fill time",
                "trend_up_age_bars": "consecutive TREND_UP candles ending at entry signal candle, inclusive",
                "trend_up_age_censored": "true when the streak reaches the first candle available in the backtest DDS range",
                "ema_slope_10": "(current EMA - EMA 9 bars earlier) / EMA 9 bars earlier, matching calculate_ema_slope(..., lookback=10)",
                "time_to_trend_down_hours": "hours from entry signal candle to first TREND_DOWN candle occurring no later than the exit signal candle",
            },
        },
        "reports": [asdict(report) for report in reports],
    }
    json_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")

    fieldnames = list(asdict(reports[0].records[0]).keys()) if reports and reports[0].records else []
    with csv_file.open("w", newline="", encoding="utf-8-sig") as handle:
        if fieldnames:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for report in reports:
                for record in report.records:
                    writer.writerow({k: _json_default(v) for k, v in asdict(record).items()})

    print(f"json_artifact              : {json_file}")
    print(f"csv_artifact               : {csv_file}")


if __name__ == "__main__":
    asyncio.run(main())
