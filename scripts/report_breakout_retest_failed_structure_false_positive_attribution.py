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
from app.backtest.walk_forward import WalkForwardConfig, generate_walk_forward_windows, run_fixed_parameter_walk_forward
from app.reporting.breakout_retest_attribution import reconstruct_breakout_retest_trades
from app.reporting.breakout_retest_failed_structure_counterfactual import build_failed_structure_counterfactual
from app.reporting.breakout_retest_failed_structure_false_positive_attribution import (
    build_false_positive_attribution_trade,
    build_false_positive_stats,
    categorical_counts,
)
from app.strategies.breakout_retest import BreakoutRetestStrategy
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED_BASE = {
    "BTCUSDT": (Decimal("-0.1391016840064235879634907285"), 49),
    "ETHUSDT": (Decimal("-3.153621560329388837431488648"), 64),
}
EXPECTED_STRUCTURAL = {
    "BTCUSDT": (12, Decimal("-0.5530745764761359024954602469"), 4, 8),
    "ETHUSDT": (15, Decimal("-0.5422653197303093302973304478"), 2, 11),
}
TOLERANCE = Decimal("1E-24")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _print_stats(items) -> None:
    print("DESCRIPTIVE ATTRIBUTION")
    print("-----------------------")
    stats = build_false_positive_stats(tuple(items))
    features = (
        "breakout_strength_pct",
        "retest_depth_pct",
        "bars_to_retest",
        "return_24h_pct",
        "mfe_24h_pct",
        "mae_24h_pct",
        "distance_to_ema20_pct",
        "distance_to_ema50_pct",
        "distance_to_breakout_level_pct",
        "ema20_slope_1bar_pct",
        "ema50_slope_1bar_pct",
        "holding_after_24h_bars",
        "future_mfe_after_24h_pct",
        "future_mae_after_24h_pct",
    )
    for feature in features:
        print(feature)
        for stat in stats:
            if stat.feature != feature or stat.group == "ALL_TRIGGERED":
                continue
            print(
                f"  {stat.group:20} n={stat.count:2d} mean={stat.mean} "
                f"median={stat.median} p25={stat.p25} p75={stat.p75}"
            )
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only attribution of false positives from failed-structure counterfactual v1"
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
        raise ValueError("False-positive attribution supports frozen 1h experiment only")

    start, end = parse_datetime(args.start), parse_datetime(args.end)
    config = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=args.initial_balance,
        random_seed=args.seed,
    )
    windows = generate_walk_forward_windows(start, end, config)
    payload: list[dict[str, Any]] = []
    all_items = []

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
        expected_pnl, expected_trades = EXPECTED_BASE[symbol]
        if abs(aggregate.total_oos_pnl - expected_pnl) > TOLERANCE or aggregate.total_oos_trades != expected_trades:
            raise ValueError(f"Frozen Breakout Retest reproduction failed for {symbol}")

        trades = []
        candles_by_window: dict[int, list[dict[str, Any]]] = {}
        for window in windows:
            test_candles = [c for c in candles if window.test_start <= c["open_time"] < window.test_end]
            candles_by_window[window.index] = test_candles
            result = BacktestEngine(
                BacktestConfig(initial_balance=config.initial_balance, random_seed=config.random_seed)
            ).run(
                candles=test_candles,
                strategy=BreakoutRetestStrategy([symbol]),
                indicator_provider=lambda candle, index: candle["indicators"],
            )
            trades.extend(reconstruct_breakout_retest_trades(result, symbol=symbol, window_index=window.index))

        structural = build_failed_structure_counterfactual(
            tuple(trades), candles_by_window=candles_by_window, symbol=symbol, base_seed=args.seed
        )
        exp_triggered, exp_cf_pnl, exp_sacrificed, exp_saved = EXPECTED_STRUCTURAL[symbol]
        if (
            structural.triggered != exp_triggered
            or abs(structural.counterfactual_pnl - exp_cf_pnl) > TOLERANCE
            or structural.sacrificed_winners != exp_sacrificed
            or structural.saved_losers != exp_saved
        ):
            raise ValueError(
                f"Failed-structure counterfactual reproduction failed for {symbol}: "
                f"triggered={structural.triggered} cf={structural.counterfactual_pnl} "
                f"sacrificed={structural.sacrificed_winners} saved={structural.saved_losers}"
            )

        trades_by_key = {(trade.window_index, trade.entry_fill_time): trade for trade in trades}
        items = []
        for result in structural.trades_detail:
            if not result.triggered:
                continue
            key = (result.window_index, result.entry_fill_time)
            trade = trades_by_key.get(key)
            if trade is None:
                raise ValueError(f"Triggered result has no source trade: {key}")
            items.append(
                build_false_positive_attribution_trade(
                    trade, result, candles=candles_by_window[result.window_index]
                )
            )

        if len(items) != structural.triggered:
            raise ValueError(
                f"Triggered attribution reconciliation failed for {symbol}: "
                f"expected={structural.triggered} actual={len(items)}"
            )
        group_counts = {group: sum(item.group == group for item in items) for group in (
            "SAVED_LOSER", "SACRIFICED_WINNER", "OTHER_TRIGGER"
        )}
        if group_counts["SAVED_LOSER"] != structural.saved_losers or group_counts["SACRIFICED_WINNER"] != structural.sacrificed_winners:
            raise ValueError(f"Outcome group reconciliation failed for {symbol}: {group_counts}")

        print(f"\nFAILED STRUCTURE FALSE-POSITIVE ATTRIBUTION: {symbol}")
        print("=" * (43 + len(symbol)))
        print(f"triggered          : {len(items)}")
        print(f"saved_loser        : {group_counts['SAVED_LOSER']}")
        print(f"sacrificed_winner  : {group_counts['SACRIFICED_WINNER']}")
        print(f"other_trigger      : {group_counts['OTHER_TRIGGER']}")
        for group in ("SAVED_LOSER", "SACRIFICED_WINNER", "OTHER_TRIGGER"):
            print(f"exit_reason {group:20}: {categorical_counts(tuple(items), field='actual_exit_reason', group=group)}")
            print(f"regime_24h  {group:20}: {categorical_counts(tuple(items), field='regime_24h', group=group)}")
        print()
        _print_stats(items)

        payload.append({
            "symbol": symbol,
            "reproduction": {
                "triggered": structural.triggered,
                "counterfactual_pnl": structural.counterfactual_pnl,
                "saved_losers": structural.saved_losers,
                "sacrificed_winners": structural.sacrificed_winners,
            },
            "group_counts": group_counts,
            "exit_reason_counts": {
                group: categorical_counts(tuple(items), field="actual_exit_reason", group=group)
                for group in ("SAVED_LOSER", "SACRIFICED_WINNER", "OTHER_TRIGGER")
            },
            "regime_24h_counts": {
                group: categorical_counts(tuple(items), field="regime_24h", group=group)
                for group in ("SAVED_LOSER", "SACRIFICED_WINNER", "OTHER_TRIGGER")
            },
            "stats": [asdict(stat) for stat in build_false_positive_stats(tuple(items))],
            "trades": [asdict(item) for item in items],
        })
        all_items.extend(items)

    print("\nCOMBINED FAILED STRUCTURE FALSE-POSITIVE ATTRIBUTION")
    print("===================================================")
    print(f"triggered          : {len(all_items)}")
    print(f"saved_loser        : {sum(item.group == 'SAVED_LOSER' for item in all_items)}")
    print(f"sacrificed_winner  : {sum(item.group == 'SACRIFICED_WINNER' for item in all_items)}")
    print(f"other_trigger      : {sum(item.group == 'OTHER_TRIGGER' for item in all_items)}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"breakout_retest_failed_structure_false_positive_attribution_{timestamp}.json"
    csv_path = output_dir / f"breakout_retest_failed_structure_false_positive_attribution_{timestamp}.csv"
    json_path.write_text(json.dumps({
        "metadata": {
            "source_rule": "failed_breakout_structure_counterfactual_v1",
            "purpose": "read-only false-positive attribution; no new trading rule",
            "future_features_are_explanatory_only": True,
        },
        "symbols": payload,
        "combined": {
            "triggered": len(all_items),
            "saved_loser": sum(item.group == "SAVED_LOSER" for item in all_items),
            "sacrificed_winner": sum(item.group == "SACRIFICED_WINNER" for item in all_items),
            "other_trigger": sum(item.group == "OTHER_TRIGGER" for item in all_items),
        },
    }, indent=2, default=_json_default), encoding="utf-8")
    rows = [asdict(item) for item in all_items]
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader(); writer.writerows(rows)
    print(f"json_artifact: {json_path}")
    print(f"csv_artifact : {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
