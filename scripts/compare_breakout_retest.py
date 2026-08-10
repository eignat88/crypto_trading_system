from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.walk_forward import WalkForwardConfig, run_fixed_parameter_walk_forward
from app.strategies.breakout_retest import PARAMETERS_VERSION, BreakoutRetestStrategy
from scripts.run_backtest import load_candles, parse_datetime

BASELINE_VERSION = "trend_dca_v1"
BASELINE_EXPECTED = {
    "BTCUSDT": {
        "pnl": Decimal("-1.919472385900019863816920150"),
        "trades": 54,
    },
    "ETHUSDT": {
        "pnl": Decimal("-3.468563029505904349952368764"),
        "trades": 66,
    },
}
BASELINE_PROFITABLE_WINDOWS = 7
MIN_COMBINED_TRADES = 30
MIN_TRADES_PER_SYMBOL = 10
PNL_TOLERANCE = Decimal("1E-24")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _validate_baseline(symbol: str, baseline) -> None:
    expected = BASELINE_EXPECTED.get(symbol)
    if expected is None:
        return
    if abs(baseline.total_oos_pnl - expected["pnl"]) > PNL_TOLERANCE:
        raise ValueError(
            f"Baseline PnL reproduction failed for {symbol}: "
            f"expected={expected['pnl']} actual={baseline.total_oos_pnl}"
        )
    if baseline.total_oos_trades != expected["trades"]:
        raise ValueError(
            f"Baseline trade-count reproduction failed for {symbol}: "
            f"expected={expected['trades']} actual={baseline.total_oos_trades}"
        )


def _validate_same_windows(baseline, experiment) -> None:
    if len(baseline.windows) != len(experiment.windows):
        raise ValueError("Baseline/BreakoutRetest window count mismatch")
    for base, exp in zip(baseline.windows, experiment.windows):
        if base.window != exp.window or base.candle_count != exp.candle_count:
            raise ValueError(
                f"Baseline/BreakoutRetest window mismatch at window {base.window.index}"
            )


def _max_window_dd(result) -> Decimal:
    return max((window.max_drawdown for window in result.windows), default=Decimal("0"))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Controlled walk-forward A/B: TrendDCA v1 vs Breakout Retest v1"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        choices=["BTCUSDT", "ETHUSDT"],
    )
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

    if args.interval != "1h":
        raise ValueError("Breakout Retest v1 frozen evaluation supports only 1h")

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    config = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=args.initial_balance,
        random_seed=args.seed,
    )

    baseline_total = Decimal("0")
    experiment_total = Decimal("0")
    baseline_profitable = 0
    experiment_profitable = 0
    baseline_trades = 0
    experiment_trades = 0
    baseline_max_dd = Decimal("0")
    experiment_max_dd = Decimal("0")
    improved_symbols = 0
    sample_gate_symbols = 0
    payload_symbols: list[dict[str, Any]] = []

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
        _validate_baseline(symbol, baseline)

        experiment = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
            strategy_factory=lambda current_symbol: BreakoutRetestStrategy([current_symbol]),
        )
        _validate_same_windows(baseline, experiment)

        delta = experiment.total_oos_pnl - baseline.total_oos_pnl
        if delta > 0:
            improved_symbols += 1
        if experiment.total_oos_trades >= MIN_TRADES_PER_SYMBOL:
            sample_gate_symbols += 1

        print()
        print(f"A/B WALK-FORWARD BREAKOUT RETEST: {symbol}")
        print("=" * (35 + len(symbol)))
        print(f"baseline_version      : {BASELINE_VERSION}")
        print(f"experiment_version    : {PARAMETERS_VERSION}")
        print(f"windows               : {len(baseline.windows)}")
        print(f"baseline_oos_pnl      : {baseline.total_oos_pnl}")
        print(f"experiment_oos_pnl    : {experiment.total_oos_pnl}")
        print(f"pnl_delta             : {delta}")
        print(f"baseline_profitable   : {baseline.profitable_windows}")
        print(f"experiment_profitable : {experiment.profitable_windows}")
        print(f"baseline_trades       : {baseline.total_oos_trades}")
        print(f"experiment_trades     : {experiment.total_oos_trades}")
        print(
            f"sample_gate_>=10      : "
            f"{experiment.total_oos_trades >= MIN_TRADES_PER_SYMBOL}"
        )
        print()
        print("WINDOW COMPARISON")
        print("-----------------")

        window_payload: list[dict[str, Any]] = []
        for base, exp in zip(baseline.windows, experiment.windows):
            print(
                f"{base.window.index:02d} "
                f"test={base.window.test_start.date()}..{base.window.test_end.date()} "
                f"base_pnl={base.total_pnl} breakout_pnl={exp.total_pnl} "
                f"delta={exp.total_pnl - base.total_pnl} "
                f"base_trades={base.total_trades} breakout_trades={exp.total_trades} "
                f"base_dd={base.max_drawdown} breakout_dd={exp.max_drawdown}"
            )
            window_payload.append(
                {
                    "window": asdict(base.window),
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
        baseline_max_dd = max(baseline_max_dd, _max_window_dd(baseline))
        experiment_max_dd = max(experiment_max_dd, _max_window_dd(experiment))

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
                "sample_gate_passed": experiment.total_oos_trades >= MIN_TRADES_PER_SYMBOL,
                "windows": window_payload,
            }
        )

    total_windows = sum(len(item["windows"]) for item in payload_symbols)
    combined_sample_gate = experiment_trades >= MIN_COMBINED_TRADES
    all_symbol_sample_gates = sample_gate_symbols == len(args.symbols)
    profitable_window_gate = experiment_profitable >= BASELINE_PROFITABLE_WINDOWS
    combined_improved = experiment_total > baseline_total
    all_symbols_improved = improved_symbols == len(args.symbols)
    dd_not_worse = experiment_max_dd <= baseline_max_dd

    print()
    print("COMBINED BREAKOUT RETEST A/B SUMMARY")
    print("====================================")
    print(f"symbols                     : {','.join(args.symbols)}")
    print(f"total_windows               : {total_windows}")
    print(f"baseline_total_oos_pnl      : {baseline_total}")
    print(f"experiment_total_oos_pnl    : {experiment_total}")
    print(f"combined_pnl_delta          : {experiment_total - baseline_total}")
    print(f"baseline_profitable         : {baseline_profitable}")
    print(f"experiment_profitable       : {experiment_profitable}")
    print(f"baseline_trades             : {baseline_trades}")
    print(f"experiment_trades           : {experiment_trades}")
    print(f"baseline_max_window_dd      : {baseline_max_dd}")
    print(f"experiment_max_window_dd    : {experiment_max_dd}")
    print(f"symbols_with_pnl_improvement: {improved_symbols}/{len(args.symbols)}")
    print()
    print("PRE-SPECIFIED GATES")
    print("-------------------")
    print(f"all_symbols_pnl_improved    : {all_symbols_improved}")
    print(f"combined_pnl_improved       : {combined_improved}")
    print(f"profitable_windows_>=7      : {profitable_window_gate}")
    print(f"max_window_dd_not_worse     : {dd_not_worse}")
    print(f"combined_trades_>=30        : {combined_sample_gate}")
    print(f"each_symbol_trades_>=10     : {all_symbol_sample_gates}")

    output_dir = Path("artifacts/walk_forward/experiments")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"breakout_retest_v1_ab_{args.interval}_{timestamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(timezone.utc),
                    "baseline_version": BASELINE_VERSION,
                    "experiment_version": PARAMETERS_VERSION,
                    "specification": "docs/strategy_breakout_retest_v1.md",
                    "exchange": args.exchange,
                    "symbols": args.symbols,
                    "interval": args.interval,
                    "start": start,
                    "end": end,
                    "walk_forward_config": asdict(config),
                    "parameter_optimization": False,
                },
                "pre_specified_gates": {
                    "min_combined_trades": MIN_COMBINED_TRADES,
                    "min_trades_per_symbol": MIN_TRADES_PER_SYMBOL,
                    "min_profitable_windows": BASELINE_PROFITABLE_WINDOWS,
                    "all_symbols_pnl_improved": all_symbols_improved,
                    "combined_pnl_improved": combined_improved,
                    "profitable_windows_passed": profitable_window_gate,
                    "max_window_dd_not_worse": dd_not_worse,
                    "combined_sample_gate_passed": combined_sample_gate,
                    "each_symbol_sample_gate_passed": all_symbol_sample_gates,
                },
                "summary": {
                    "baseline_total_oos_pnl": baseline_total,
                    "experiment_total_oos_pnl": experiment_total,
                    "combined_pnl_delta": experiment_total - baseline_total,
                    "baseline_profitable_windows": baseline_profitable,
                    "experiment_profitable_windows": experiment_profitable,
                    "baseline_trades": baseline_trades,
                    "experiment_trades": experiment_trades,
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
