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

from app.backtest.walk_forward import WalkForwardConfig
from app.reporting.entry_filter_counterfactual import run_entry_filter_counterfactual
from scripts.run_backtest import load_candles, parse_datetime


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _print_features(title: str, summary) -> None:
    print()
    print(title)
    print("-" * len(title))
    for key, value in asdict(summary).items():
        print(f"{key:30}: {value}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Counterfactual diagnosis of baseline OOS entries against TRAIN EMA200 slope p75"
    )
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"], choices=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--train-days", type=int, default=180)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--initial-balance", type=Decimal, default=Decimal("500"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    config = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=args.initial_balance,
        random_seed=args.seed,
    )

    reports = []
    for symbol in args.symbols:
        candles = await load_candles(args.exchange, symbol, args.interval, start, end)
        report = run_entry_filter_counterfactual(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
        )
        reports.append(report)

        print()
        print(f"ENTRY FILTER COUNTERFACTUAL: {symbol}")
        print("=" * (29 + len(symbol)))
        print(f"baseline_oos_pnl      : {report.baseline_oos_pnl}")
        print(f"total_trades          : {report.total_trades}")
        print(f"PASS_WINNER           : {report.pass_winner}")
        print(f"PASS_TD_LOSS          : {report.pass_td_loss}")
        print(f"PASS_OTHER            : {report.pass_other}")
        print(f"FILTERED_WINNER       : {report.filtered_winner}")
        print(f"FILTERED_TD_LOSS      : {report.filtered_td_loss}")
        print(f"FILTERED_OTHER        : {report.filtered_other}")
        print(f"filtered_total        : {report.filtered_total}")
        print(f"filtered_winner_share : {report.filtered_winner_share}")
        print(f"filtered_td_loss_share: {report.filtered_td_loss_share}")

        _print_features("FILTERED WINNERS", report.filtered_winner_features)
        _print_features("FILTERED TREND_DOWN LOSSES", report.filtered_td_loss_features)

        print()
        print("FILTERED TRADES")
        print("---------------")
        for trade in report.trades:
            if trade.would_pass_p75:
                continue
            print(
                f"w{trade.window_index:02d} {trade.filter_group:16} "
                f"entry={trade.entry_signal_time.isoformat()} "
                f"p75={trade.train_p75} slope={trade.entry_ema200_slope_10} "
                f"margin={trade.slope_margin_to_threshold} pnl={trade.realized_pnl} "
                f"reason={trade.exit_reason}"
            )

    combined_trades = [trade for report in reports for trade in report.trades]
    combined_filtered_winners = sum(report.filtered_winner for report in reports)
    combined_filtered_losses = sum(report.filtered_td_loss for report in reports)
    combined_filtered_other = sum(report.filtered_other for report in reports)
    combined_total = len(combined_trades)
    combined_filtered = combined_filtered_winners + combined_filtered_losses + combined_filtered_other

    print()
    print("COMBINED COUNTERFACTUAL SUMMARY")
    print("===============================")
    print(f"symbols             : {','.join(args.symbols)}")
    print(f"baseline_trades     : {combined_total}")
    print(f"filtered_total      : {combined_filtered}")
    print(f"filtered_winners    : {combined_filtered_winners}")
    print(f"filtered_td_losses  : {combined_filtered_losses}")
    print(f"filtered_other      : {combined_filtered_other}")
    print(f"filtered_winner_rate: {Decimal(combined_filtered_winners) / Decimal(combined_filtered) if combined_filtered else Decimal('0')}")
    print(f"filtered_loss_rate  : {Decimal(combined_filtered_losses) / Decimal(combined_filtered) if combined_filtered else Decimal('0')}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"entry_filter_counterfactual_{stamp}.json"
    csv_path = output_dir / f"entry_filter_counterfactual_{stamp}.csv"

    payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc),
            "definition": "Baseline OOS trades labelled against frozen TRAIN p75; baseline outcomes are not recomputed",
            "exchange": args.exchange,
            "symbols": args.symbols,
            "interval": args.interval,
            "start": start,
            "end": end,
            "walk_forward_config": asdict(config),
        },
        "reports": [asdict(report) for report in reports],
    }
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    fieldnames = list(asdict(combined_trades[0]).keys()) if combined_trades else []
    if fieldnames:
        with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for trade in combined_trades:
                writer.writerow({key: _json_default(value) for key, value in asdict(trade).items()})

    print(f"json_artifact        : {json_path}")
    print(f"csv_artifact         : {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
