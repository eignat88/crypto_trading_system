from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.ema200_slope_p75_walk_forward import (
    run_ema200_slope_train_p75_walk_forward,
)
from app.backtest.walk_forward import WalkForwardConfig, run_fixed_parameter_walk_forward
from app.strategies.trend_dca_ema200_slope_p75 import EXPERIMENT_PARAMETERS_VERSION
from scripts.run_backtest import load_candles, parse_datetime

BASELINE_VERSION = "trend_dca_v1"


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _validate_same_windows(baseline, experiment) -> None:
    if len(baseline.windows) != len(experiment.windows):
        raise ValueError("Baseline/experiment window count mismatch")
    for base, exp in zip(baseline.windows, experiment.windows):
        if base.window != exp.window or base.candle_count != exp.candle_count:
            raise ValueError(
                f"Baseline/experiment window mismatch at {base.window.index}"
            )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare TrendDCA baseline with TRAIN-derived EMA200 slope p75 entry filter"
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

    payload_symbols = []
    baseline_total = Decimal("0")
    experiment_total = Decimal("0")
    baseline_profitable = 0
    experiment_profitable = 0
    baseline_trades = 0
    experiment_trades = 0
    baseline_max_dd = Decimal("0")
    experiment_max_dd = Decimal("0")
    improved_symbols = 0

    for symbol in args.symbols:
        candles = await load_candles(args.exchange, symbol, args.interval, start, end)
        baseline = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
        )
        experiment_result = run_ema200_slope_train_p75_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
        )
        experiment = experiment_result.result
        _validate_same_windows(baseline, experiment)

        delta = experiment.total_oos_pnl - baseline.total_oos_pnl
        if delta > 0:
            improved_symbols += 1

        print()
        print(f"A/B WALK-FORWARD EMA200 TRAIN P75: {symbol}")
        print("=" * (33 + len(symbol)))
        print(f"baseline_version          : {BASELINE_VERSION}")
        print(f"experiment_version        : {EXPERIMENT_PARAMETERS_VERSION}")
        print(f"windows                   : {len(baseline.windows)}")
        print(f"baseline_oos_pnl          : {baseline.total_oos_pnl}")
        print(f"experiment_oos_pnl        : {experiment.total_oos_pnl}")
        print(f"pnl_delta                 : {delta}")
        print(f"baseline_profitable       : {baseline.profitable_windows}")
        print(f"experiment_profitable     : {experiment.profitable_windows}")
        print(f"baseline_trades           : {baseline.total_oos_trades}")
        print(f"experiment_trades         : {experiment.total_oos_trades}")
        print()
        print("WINDOW COMPARISON")
        print("-----------------")

        threshold_by_window = {item.window_index: item for item in experiment_result.thresholds}
        window_payload = []
        for base, exp in zip(baseline.windows, experiment.windows):
            threshold = threshold_by_window[base.window.index]
            print(
                f"{base.window.index:02d} "
                f"test={base.window.test_start.date()}..{base.window.test_end.date()} "
                f"train_opportunities={threshold.train_opportunities} "
                f"train_p75={threshold.threshold} "
                f"base_pnl={base.total_pnl} exp_pnl={exp.total_pnl} "
                f"delta={exp.total_pnl - base.total_pnl} "
                f"base_trades={base.total_trades} exp_trades={exp.total_trades} "
                f"base_dd={base.max_drawdown} exp_dd={exp.max_drawdown}"
            )
            window_payload.append(
                {
                    "window": asdict(base.window),
                    "train_opportunities": threshold.train_opportunities,
                    "train_p75": threshold.threshold,
                    "baseline": asdict(base),
                    "experiment": asdict(exp),
                    "pnl_delta": exp.total_pnl - base.total_pnl,
                }
            )

        baseline_total += baseline.total_oos_pnl
        experiment_total += experiment.total_oos_pnl
        baseline_profitable += baseline.profitable_windows
        experiment_profitable += experiment.profitable_windows
        baseline_trades += baseline.total_oos_trades
        experiment_trades += experiment.total_oos_trades
        baseline_max_dd = max(baseline_max_dd, *(w.max_drawdown for w in baseline.windows))
        experiment_max_dd = max(experiment_max_dd, *(w.max_drawdown for w in experiment.windows))

        payload_symbols.append(
            {
                "symbol": symbol,
                "baseline_total_oos_pnl": baseline.total_oos_pnl,
                "experiment_total_oos_pnl": experiment.total_oos_pnl,
                "pnl_delta": delta,
                "baseline_profitable_windows": baseline.profitable_windows,
                "experiment_profitable_windows": experiment.profitable_windows,
                "baseline_trades": baseline.total_oos_trades,
                "experiment_trades": experiment.total_oos_trades,
                "windows": window_payload,
            }
        )

    total_windows = len(args.symbols) * len(payload_symbols[0]["windows"])
    print()
    print("COMBINED A/B SUMMARY")
    print("====================")
    print(f"symbols                     : {','.join(args.symbols)}")
    print(f"total_windows               : {total_windows}")
    print(f"baseline_total_oos_pnl      : {baseline_total}")
    print(f"experiment_total_oos_pnl    : {experiment_total}")
    print(f"combined_pnl_delta          : {experiment_total - baseline_total}")
    print(f"baseline_profitable         : {baseline_profitable}")
    print(f"experiment_profitable       : {experiment_profitable}")
    print(f"baseline_trades             : {baseline_trades}")
    print(f"experiment_trades           : {experiment_trades}")
    print(f"trade_retention_rate        : {Decimal(experiment_trades) / Decimal(baseline_trades) if baseline_trades else Decimal('0')}")
    print(f"baseline_max_window_dd      : {baseline_max_dd}")
    print(f"experiment_max_window_dd    : {experiment_max_dd}")
    print(f"symbols_with_pnl_improvement: {improved_symbols}/{len(args.symbols)}")

    output_dir = Path("artifacts/walk_forward/experiments")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"ema200_slope_train_p75_ab_{args.interval}_{timestamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(UTC),
                    "baseline_version": BASELINE_VERSION,
                    "experiment_version": EXPERIMENT_PARAMETERS_VERSION,
                    "threshold_method": "p75 of TRAIN baseline-compatible entry opportunities",
                    "exchange": args.exchange,
                    "symbols": args.symbols,
                    "interval": args.interval,
                    "start": start,
                    "end": end,
                    "walk_forward_config": asdict(config),
                },
                "summary": {
                    "baseline_total_oos_pnl": baseline_total,
                    "experiment_total_oos_pnl": experiment_total,
                    "combined_pnl_delta": experiment_total - baseline_total,
                    "baseline_profitable_windows": baseline_profitable,
                    "experiment_profitable_windows": experiment_profitable,
                    "baseline_trades": baseline_trades,
                    "experiment_trades": experiment_trades,
                    "trade_retention_rate": Decimal(experiment_trades) / Decimal(baseline_trades) if baseline_trades else Decimal("0"),
                    "baseline_max_window_dd": baseline_max_dd,
                    "experiment_max_window_dd": experiment_max_dd,
                    "symbols_with_pnl_improvement": improved_symbols,
                },
                "symbols": payload_symbols,
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print(f"artifact                    : {artifact}")


if __name__ == "__main__":
    asyncio.run(main())
