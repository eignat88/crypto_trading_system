from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.walk_forward import WalkForwardConfig
from app.reporting.entry_filter_counterfactual import run_entry_filter_counterfactual
from app.reporting.trend_momentum_decay import HORIZONS, build_trend_momentum_decay
from scripts.run_backtest import load_candles, parse_datetime


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _print_summary(report) -> None:
    print()
    print(f"TREND MOMENTUM DECAY: {report.symbol}")
    print("=" * (22 + len(report.symbol)))
    print(f"filtered_winners   : {report.source_filtered_winners}")
    print(f"filtered_td_losses : {report.source_filtered_td_losses}")

    by_key = {(item.group, item.horizon_hours): item for item in report.summaries}
    for horizon in HORIZONS:
        print()
        print(f"HORIZON {horizon}h")
        print("-" * 24)
        for group in ("FILTERED_WINNER", "FILTERED_TD_LOSS"):
            item = by_key[(group, horizon)]
            print(group)
            print(f"  trades                      : {item.trades}")
            print(f"  avg_pnl                     : {item.average_pnl}")
            print(f"  avg_ema20_slope_delta       : {item.average_ema20_slope_delta}")
            print(f"  median_ema20_slope_delta    : {item.median_ema20_slope_delta}")
            print(f"  ema20_decay_rate            : {item.ema20_decay_rate}")
            print(f"  avg_ema50_slope_delta       : {item.average_ema50_slope_delta}")
            print(f"  median_ema50_slope_delta    : {item.median_ema50_slope_delta}")
            print(f"  ema50_decay_rate            : {item.ema50_decay_rate}")
            print(f"  avg_ema200_slope_delta      : {item.average_ema200_slope_delta}")
            print(f"  median_ema200_slope_delta   : {item.median_ema200_slope_delta}")
            print(f"  ema200_decay_rate           : {item.ema200_decay_rate}")
            print(f"  avg_close_to_ema20_delta    : {item.average_close_to_ema20_delta}")
            print(f"  avg_close_to_ema50_delta    : {item.average_close_to_ema50_delta}")
            print(f"  avg_close_to_ema200_delta   : {item.average_close_to_ema200_delta}")
            print(f"  avg_confidence_delta        : {item.average_regime_confidence_delta}")
            print(f"  confidence_decay_rate       : {item.confidence_decay_rate}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose pre-entry trend momentum decay for filtered baseline trades")
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

    payload = []
    combined_records = []
    for symbol in args.symbols:
        candles = await load_candles(args.exchange, symbol, args.interval, start, end)
        counterfactual = run_entry_filter_counterfactual(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
        )
        report = build_trend_momentum_decay(candles=candles, counterfactual=counterfactual)
        _print_summary(report)
        payload.append({"symbol": symbol, "counterfactual": {"baseline_oos_pnl": counterfactual.baseline_oos_pnl, "total_trades": counterfactual.total_trades}, "report": asdict(report)})
        combined_records.extend(report.records)

    print()
    print("COMBINED MOMENTUM DECAY COUNTS")
    print("==============================")
    print(f"symbols             : {','.join(args.symbols)}")
    print(f"filtered_winners    : {sum(1 for r in combined_records if r.filter_group == 'FILTERED_WINNER' and r.horizon_hours == 6)}")
    print(f"filtered_td_losses  : {sum(1 for r in combined_records if r.filter_group == 'FILTERED_TD_LOSS' and r.horizon_hours == 6)}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"trend_momentum_decay_{timestamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(timezone.utc),
                    "exchange": args.exchange,
                    "symbols": args.symbols,
                    "interval": args.interval,
                    "start": start,
                    "end": end,
                    "horizons_hours": HORIZONS,
                    "delta_definition": "entry_value - value_h_hours_before_entry",
                    "walk_forward_config": asdict(config),
                },
                "symbols": payload,
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print(f"artifact            : {artifact}")


if __name__ == "__main__":
    asyncio.run(main())
