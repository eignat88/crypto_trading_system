from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from run_backtest import load_candles, parse_datetime

from app.backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    run_fixed_parameter_walk_forward,
)
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy
from app.strategies.trend_dca_confirm3 import (
    EXPERIMENT_PARAMETERS_VERSION,
    TrendDCAConfirm3Strategy,
)

BASELINE_VERSION = "trend_dca_v1"


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _baseline_factory(symbol: str) -> TrendDCAStrategy:
    return TrendDCAStrategy(
        symbols=[symbol],
        config=DCAConfig(parameters_version=BASELINE_VERSION),
    )


def _confirm3_factory(symbol: str) -> TrendDCAConfirm3Strategy:
    return TrendDCAConfirm3Strategy(symbols=[symbol])


def _max_window_drawdown(result: WalkForwardResult) -> Decimal:
    return max((item.max_drawdown for item in result.windows), default=Decimal("0"))


def _result_payload(result: WalkForwardResult) -> dict[str, Any]:
    return {
        "total_oos_pnl": result.total_oos_pnl,
        "profitable_windows": result.profitable_windows,
        "losing_windows": result.losing_windows,
        "flat_windows": result.flat_windows,
        "profitable_window_rate": result.profitable_window_rate,
        "total_oos_trades": result.total_oos_trades,
        "max_window_drawdown": _max_window_drawdown(result),
        "windows": [
            {
                "index": item.window.index,
                "test_start": item.window.test_start,
                "test_end": item.window.test_end,
                "candle_count": item.candle_count,
                "total_pnl": item.total_pnl,
                "total_trades": item.total_trades,
                "win_rate": item.win_rate,
                "profit_factor": item.profit_factor,
                "max_drawdown": item.max_drawdown,
            }
            for item in result.windows
        ],
    }


def _print_symbol_comparison(
    symbol: str,
    baseline: WalkForwardResult,
    experiment: WalkForwardResult,
) -> None:
    print()
    print(f"A/B WALK-FORWARD: {symbol}")
    print("=" * (18 + len(symbol)))
    print(f"baseline_version          : {BASELINE_VERSION}")
    print(f"experiment_version        : {EXPERIMENT_PARAMETERS_VERSION}")
    print(f"windows                   : {len(baseline.windows)}")
    print(f"baseline_oos_pnl          : {baseline.total_oos_pnl}")
    print(f"experiment_oos_pnl        : {experiment.total_oos_pnl}")
    print(f"pnl_delta                 : {experiment.total_oos_pnl - baseline.total_oos_pnl}")
    print(f"baseline_profitable       : {baseline.profitable_windows}")
    print(f"experiment_profitable     : {experiment.profitable_windows}")
    print(f"baseline_window_rate      : {baseline.profitable_window_rate}")
    print(f"experiment_window_rate    : {experiment.profitable_window_rate}")
    print(f"baseline_max_window_dd    : {_max_window_drawdown(baseline)}")
    print(f"experiment_max_window_dd  : {_max_window_drawdown(experiment)}")
    print(f"baseline_trades           : {baseline.total_oos_trades}")
    print(f"experiment_trades         : {experiment.total_oos_trades}")
    print()
    print("WINDOW COMPARISON")
    print("-----------------")
    for base_window, exp_window in zip(baseline.windows, experiment.windows, strict=True):
        if base_window.window != exp_window.window:
            raise RuntimeError("Baseline and experiment walk-forward boundaries differ")
        print(
            f"{base_window.window.index:02d} "
            f"test={base_window.window.test_start.date()}..{base_window.window.test_end.date()} "
            f"base_pnl={base_window.total_pnl} exp_pnl={exp_window.total_pnl} "
            f"delta={exp_window.total_pnl - base_window.total_pnl} "
            f"base_pf={base_window.profit_factor} exp_pf={exp_window.profit_factor} "
            f"base_dd={base_window.max_drawdown} exp_dd={exp_window.max_drawdown}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compare TrendDCA baseline against the versioned TREND_DOWN "
            "3-consecutive-bar confirmation experiment on identical OOS windows"
        )
    )
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        choices=["BTCUSDT", "ETHUSDT"],
    )
    parser.add_argument("--interval", default="1h", choices=["5m", "15m", "1h", "4h", "1d"])
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--train-days", type=int, default=180)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--initial-balance", default="500")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    config = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=Decimal(args.initial_balance),
        random_seed=args.seed,
    )

    comparisons: dict[str, dict[str, WalkForwardResult]] = {}

    for symbol in args.symbols:
        candles = await load_candles(
            exchange=args.exchange,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
        )

        baseline = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
            strategy_factory=_baseline_factory,
        )
        experiment = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
            strategy_factory=_confirm3_factory,
        )

        if len(baseline.windows) != len(experiment.windows):
            raise RuntimeError("Baseline and experiment produced different window counts")
        comparisons[symbol] = {"baseline": baseline, "experiment": experiment}
        _print_symbol_comparison(symbol, baseline, experiment)

    baseline_total_pnl = sum(
        (item["baseline"].total_oos_pnl for item in comparisons.values()),
        Decimal("0"),
    )
    experiment_total_pnl = sum(
        (item["experiment"].total_oos_pnl for item in comparisons.values()),
        Decimal("0"),
    )
    baseline_profitable = sum(
        item["baseline"].profitable_windows for item in comparisons.values()
    )
    experiment_profitable = sum(
        item["experiment"].profitable_windows for item in comparisons.values()
    )
    total_windows = sum(len(item["baseline"].windows) for item in comparisons.values())
    baseline_max_dd = max(
        (_max_window_drawdown(item["baseline"]) for item in comparisons.values()),
        default=Decimal("0"),
    )
    experiment_max_dd = max(
        (_max_window_drawdown(item["experiment"]) for item in comparisons.values()),
        default=Decimal("0"),
    )

    print()
    print("COMBINED A/B SUMMARY")
    print("====================")
    print(f"symbols                    : {','.join(args.symbols)}")
    print(f"total_windows              : {total_windows}")
    print(f"baseline_total_oos_pnl     : {baseline_total_pnl}")
    print(f"experiment_total_oos_pnl   : {experiment_total_pnl}")
    print(f"combined_pnl_delta         : {experiment_total_pnl - baseline_total_pnl}")
    print(f"baseline_profitable        : {baseline_profitable}")
    print(f"experiment_profitable      : {experiment_profitable}")
    print(
        "baseline_window_rate        : "
        f"{Decimal(baseline_profitable) / Decimal(total_windows) if total_windows else Decimal('0')}"
    )
    print(
        "experiment_window_rate      : "
        f"{Decimal(experiment_profitable) / Decimal(total_windows) if total_windows else Decimal('0')}"
    )
    print(f"baseline_max_window_dd     : {baseline_max_dd}")
    print(f"experiment_max_window_dd   : {experiment_max_dd}")

    improved_symbols = sum(
        1
        for item in comparisons.values()
        if item["experiment"].total_oos_pnl > item["baseline"].total_oos_pnl
    )
    print(f"symbols_with_pnl_improvement: {improved_symbols}/{len(comparisons)}")

    payload = {
        "metadata": {
            "created_at": datetime.now(UTC),
            "exchange": args.exchange,
            "symbols": args.symbols,
            "interval": args.interval,
            "start": start,
            "end": end,
            "baseline_version": BASELINE_VERSION,
            "experiment_version": EXPERIMENT_PARAMETERS_VERSION,
        },
        "configuration": {
            "train_days": config.train_days,
            "test_days": config.test_days,
            "step_days": config.step_days,
            "initial_balance": config.initial_balance,
            "random_seed": config.random_seed,
        },
        "symbols": {
            symbol: {
                "baseline": _result_payload(items["baseline"]),
                "experiment": _result_payload(items["experiment"]),
                "pnl_delta": (
                    items["experiment"].total_oos_pnl
                    - items["baseline"].total_oos_pnl
                ),
            }
            for symbol, items in comparisons.items()
        },
        "combined": {
            "total_windows": total_windows,
            "baseline_total_oos_pnl": baseline_total_pnl,
            "experiment_total_oos_pnl": experiment_total_pnl,
            "combined_pnl_delta": experiment_total_pnl - baseline_total_pnl,
            "baseline_profitable_windows": baseline_profitable,
            "experiment_profitable_windows": experiment_profitable,
            "baseline_max_window_drawdown": baseline_max_dd,
            "experiment_max_window_drawdown": experiment_max_dd,
            "symbols_with_pnl_improvement": improved_symbols,
        },
    }

    output_dir = Path("artifacts/walk_forward/experiments")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_file = output_dir / f"trend_down_confirm3_ab_{args.interval}_{timestamp}.json"
    output_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    print(f"artifact                   : {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
