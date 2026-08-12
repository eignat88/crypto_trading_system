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

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.backtest.walk_forward import (
    WalkForwardConfig,
    generate_walk_forward_windows,
    run_fixed_parameter_walk_forward,
)
from app.reporting.breakout_retest_attribution import reconstruct_breakout_retest_trades
from app.reporting.breakout_retest_early_failure_snapshot import (
    EarlyFailureSnapshot,
    build_24h_snapshot,
    build_snapshot_stats,
    categorical_counts,
)
from app.strategies.breakout_retest import BreakoutRetestStrategy, PARAMETERS_VERSION
from scripts.run_backtest import load_candles, parse_datetime


EXPECTED = {
    "BTCUSDT": {"pnl": Decimal("-0.1391016840064235879634907285"), "trades": 49},
    "ETHUSDT": {"pnl": Decimal("-3.153621560329388837431488648"), "trades": 64},
}
PNL_TOLERANCE = Decimal("1E-24")
GROUPS = ("FUTURE_WINNER", "TREND_DOWN_LOSS", "MAX_HOLDING_LOSS", "ALL_LOSERS", "ALL")
FEATURES = (
    "return_24h_pct",
    "mfe_24h_pct",
    "mae_24h_pct",
    "distance_to_ema20_pct",
    "distance_to_ema50_pct",
    "distance_to_ema200_pct",
    "ema20_slope_1bar_pct",
    "ema50_slope_1bar_pct",
    "ema200_slope_1bar_pct",
    "atr_to_close_pct",
    "volatility",
    "regime_transition_count",
    "regime_changed_since_entry",
    "regime_confidence_24h",
    "distance_to_breakout_level_pct",
)


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _validate_reproduction(symbol: str, result: Any) -> None:
    expected = EXPECTED[symbol]
    if abs(result.total_oos_pnl - expected["pnl"]) > PNL_TOLERANCE:
        raise ValueError(
            f"Breakout Retest PnL reproduction failed for {symbol}: "
            f"expected={expected['pnl']} actual={result.total_oos_pnl}"
        )
    if result.total_oos_trades != expected["trades"]:
        raise ValueError(
            f"Breakout Retest trade-count reproduction failed for {symbol}: "
            f"expected={expected['trades']} actual={result.total_oos_trades}"
        )


def _print_stats(stats: tuple[Any, ...]) -> None:
    print("24H FEATURE DISTRIBUTIONS (DESCRIPTIVE ONLY)")
    print("--------------------------------------------")
    for feature in FEATURES:
        print(feature)
        for item in stats:
            if item.feature != feature or item.group not in {
                "FUTURE_WINNER", "TREND_DOWN_LOSS", "MAX_HOLDING_LOSS", "ALL_LOSERS"
            }:
                continue
            print(
                f"  {item.group:18} n={item.count:3d} mean={item.mean} "
                f"median={item.median} p25={item.p25} p75={item.p75}"
            )
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only 24h market-state snapshots for frozen Breakout Retest v1"
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

    if args.interval != "1h":
        raise ValueError("24h early-failure snapshot supports frozen 1h evaluation only")

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    config = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=args.initial_balance,
        random_seed=args.seed,
    )
    windows = generate_walk_forward_windows(start, end, config)
    all_snapshots: list[EarlyFailureSnapshot] = []
    symbol_payloads: list[dict[str, Any]] = []

    for symbol in args.symbols:
        candles = await load_candles(args.exchange, symbol, args.interval, start, end)
        aggregate = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
            strategy_factory=lambda current_symbol: BreakoutRetestStrategy([current_symbol]),
        )
        _validate_reproduction(symbol, aggregate)

        symbol_snapshots: list[EarlyFailureSnapshot] = []
        reconstructed_count = 0
        reconstructed_pnl = Decimal("0")
        for window in windows:
            test_candles = [
                candle for candle in candles
                if window.test_start <= candle["open_time"] < window.test_end
            ]
            engine = BacktestEngine(
                BacktestConfig(initial_balance=config.initial_balance, random_seed=config.random_seed)
            )
            result = engine.run(
                candles=test_candles,
                strategy=BreakoutRetestStrategy([symbol]),
                indicator_provider=lambda candle, index: candle["indicators"],
            )
            trades = reconstruct_breakout_retest_trades(
                result, symbol=symbol, window_index=window.index
            )
            reconstructed_count += len(trades)
            reconstructed_pnl += sum((trade.realized_pnl for trade in trades), Decimal("0"))
            for trade in trades:
                snapshot = build_24h_snapshot(trade, test_candles)
                if snapshot is not None:
                    symbol_snapshots.append(snapshot)

        if reconstructed_count != aggregate.total_oos_trades:
            raise ValueError(
                f"Snapshot trade reconciliation failed for {symbol}: "
                f"aggregate={aggregate.total_oos_trades} reconstructed={reconstructed_count}"
            )
        if abs(reconstructed_pnl - aggregate.total_oos_pnl) > PNL_TOLERANCE:
            raise ValueError(
                f"Snapshot PnL reconciliation failed for {symbol}: "
                f"aggregate={aggregate.total_oos_pnl} reconstructed={reconstructed_pnl}"
            )

        snapshots = tuple(symbol_snapshots)
        stats = build_snapshot_stats(snapshots)
        all_snapshots.extend(snapshots)

        print()
        print(f"EARLY FAILURE FEATURE SNAPSHOT @24H: {symbol}")
        print("=" * (38 + len(symbol)))
        print(f"strategy_version : {PARAMETERS_VERSION}")
        print(f"total_trades     : {aggregate.total_oos_trades}")
        print(f"eligible_24h     : {len(snapshots)}")
        for group in ("FUTURE_WINNER", "TREND_DOWN_LOSS", "MAX_HOLDING_LOSS", "OTHER_LOSS"):
            print(f"{group.lower():17}: {sum(1 for item in snapshots if item.group == group)}")
        print()
        print("REGIME @24H")
        print("-----------")
        for group in ("FUTURE_WINNER", "TREND_DOWN_LOSS", "MAX_HOLDING_LOSS"):
            print(f"{group:18}: {categorical_counts(snapshots, group=group)}")
        print()
        _print_stats(stats)

        symbol_payloads.append({
            "symbol": symbol,
            "total_trades": aggregate.total_oos_trades,
            "total_pnl": aggregate.total_oos_pnl,
            "eligible_24h": len(snapshots),
            "regime_24h": {
                group: categorical_counts(snapshots, group=group)
                for group in ("FUTURE_WINNER", "TREND_DOWN_LOSS", "MAX_HOLDING_LOSS")
            },
            "stats": [asdict(item) for item in stats],
            "snapshots": [asdict(item) for item in snapshots],
        })

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"breakout_retest_early_failure_snapshot_24h_{timestamp}.json"
    csv_path = output_dir / f"breakout_retest_early_failure_snapshot_24h_{timestamp}.csv"

    payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc),
            "strategy_version": PARAMETERS_VERSION,
            "snapshot_hours": 24,
            "parameter_optimization": False,
            "exit_rule_changes": False,
            "symbols": args.symbols,
            "interval": args.interval,
            "start": start,
            "end": end,
            "walk_forward_config": asdict(config),
        },
        "symbols": symbol_payloads,
    }
    json_path.write_text(json.dumps(payload, indent=2, default=_json_default), encoding="utf-8")

    rows = [asdict(item) for item in all_snapshots]
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    print("COMBINED EARLY FAILURE FEATURE SNAPSHOT @24H")
    print("============================================")
    print(f"eligible snapshots: {len(all_snapshots)}")
    print(f"json_artifact     : {json_path}")
    print(f"csv_artifact      : {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
