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
from app.backtest.walk_forward import WalkForwardConfig, generate_walk_forward_windows
from app.reporting.breakout_retest_attribution import reconstruct_breakout_retest_trades
from app.reporting.breakout_retest_exit_path import (
    HORIZONS_HOURS,
    ExitPathTrade,
    analyze_exit_path,
    build_exit_path_stats,
)
from app.strategies.breakout_retest import BreakoutRetestStrategy, PARAMETERS_VERSION
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED = {
    "BTCUSDT": {"pnl": Decimal("-0.1391016840064235879634907285"), "trades": 49},
    "ETHUSDT": {"pnl": Decimal("-3.153621560329388837431488648"), "trades": 64},
}
PNL_TOLERANCE = Decimal("1E-24")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _validate_symbol(symbol: str, pnl: Decimal, trades: int) -> None:
    expected = EXPECTED[symbol]
    if abs(pnl - expected["pnl"]) > PNL_TOLERANCE:
        raise ValueError(
            f"Breakout Retest reproduction failed for {symbol}: expected pnl={expected['pnl']} actual={pnl}"
        )
    if trades != expected["trades"]:
        raise ValueError(
            f"Breakout Retest trade-count reproduction failed for {symbol}: expected={expected['trades']} actual={trades}"
        )


def _stat_map(stats) -> dict[tuple[str, str], Any]:
    return {(item.feature, item.group): item for item in stats}


def _print_stats(symbol: str, paths: tuple[ExitPathTrade, ...]) -> None:
    stats = build_exit_path_stats(paths)
    lookup = _stat_map(stats)
    print()
    print(f"BREAKOUT RETEST EXIT PATH: {symbol}")
    print("=" * (28 + len(symbol)))
    print(f"trades: {len(paths)}")
    print()
    print("PATH DISTRIBUTIONS (DESCRIPTIVE ONLY)")
    print("------------------------------------")
    for feature in (
        "mfe_pct",
        "mae_pct",
        "bars_to_mfe",
        "bars_to_mae",
        "bars_to_trend_down",
        "max_favorable_before_trend_down_pct",
        "return_before_trend_down_pct",
        "return_6h_pct",
        "return_12h_pct",
        "return_24h_pct",
        "return_48h_pct",
    ):
        print(feature)
        for group in ("WINNER", "TREND_DOWN_LOSS", "MAX_HOLDING_LOSS", "ALL_LOSERS"):
            item = lookup[(feature, group)]
            print(
                f"  {group:18s} n={item.count:3d} mean={item.mean} median={item.median} p25={item.p25} p75={item.p75}"
            )


def _flatten_csv(path: ExitPathTrade) -> dict[str, Any]:
    row: dict[str, Any] = {
        "symbol": path.symbol,
        "window_index": path.window_index,
        "entry_time": path.entry_time.isoformat(),
        "exit_time": path.exit_time.isoformat(),
        "exit_reason": path.exit_reason,
        "realized_pnl": path.realized_pnl,
        "outcome": path.outcome,
        "entry_price": path.entry_price,
        "exit_price": path.exit_price,
        "holding_bars": path.holding_bars,
        "mfe_pct": path.mfe_pct,
        "mae_pct": path.mae_pct,
        "bars_to_mfe": path.bars_to_mfe,
        "bars_to_mae": path.bars_to_mae,
        "first_trend_down_time": None if path.first_trend_down_time is None else path.first_trend_down_time.isoformat(),
        "bars_to_trend_down": path.bars_to_trend_down,
        "max_favorable_before_trend_down_pct": path.max_favorable_before_trend_down_pct,
        "return_before_trend_down_pct": path.return_before_trend_down_pct,
    }
    snapshots = {item.horizon_hours: item for item in path.horizons}
    for horizon in HORIZONS_HOURS:
        item = snapshots.get(horizon)
        row[f"return_{horizon}h_pct"] = None if item is None else item.return_pct
        row[f"regime_{horizon}h"] = None if item is None else item.regime
        row[f"close_above_ema20_{horizon}h"] = None if item is None else item.close_above_ema20
        row[f"close_above_ema50_{horizon}h"] = None if item is None else item.close_above_ema50
        row[f"close_above_ema200_{horizon}h"] = None if item is None else item.close_above_ema200
    return row


async def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Breakout Retest exit-path diagnostics")
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
        raise ValueError("Exit-path diagnostics are frozen to 1h")

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    wf = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=args.initial_balance,
        random_seed=args.seed,
    )
    windows = generate_walk_forward_windows(start, end, wf)

    all_paths: list[ExitPathTrade] = []
    payload_symbols: list[dict[str, Any]] = []
    combined_pnl = Decimal("0")
    combined_trades = 0

    for symbol in args.symbols:
        candles = await load_candles(args.exchange, symbol, args.interval, start, end)
        symbol_paths: list[ExitPathTrade] = []
        symbol_pnl = Decimal("0")
        symbol_trades = 0

        for window in windows:
            test_candles = [c for c in candles if window.test_start <= c["open_time"] < window.test_end]
            expected_count = int((window.test_end - window.test_start).total_seconds() // 3600)
            if len(test_candles) != expected_count:
                raise ValueError(
                    f"Incomplete OOS window {window.index} for {symbol}: expected={expected_count} actual={len(test_candles)}"
                )
            strategy = BreakoutRetestStrategy([symbol])
            engine = BacktestEngine(BacktestConfig(initial_balance=args.initial_balance, random_seed=args.seed))
            result = engine.run(
                candles=test_candles,
                strategy=strategy,
                indicator_provider=lambda candle, index: candle["indicators"],
            )
            trades = reconstruct_breakout_retest_trades(result, symbol=symbol, window_index=window.index)
            if len(trades) != result.total_trades:
                raise ValueError("Attribution/backtest trade reconciliation failed")
            window_paths = tuple(analyze_exit_path(trade, test_candles) for trade in trades)
            symbol_paths.extend(window_paths)
            symbol_pnl += result.total_pnl
            symbol_trades += result.total_trades

        _validate_symbol(symbol, symbol_pnl, symbol_trades)
        paths_tuple = tuple(symbol_paths)
        _print_stats(symbol, paths_tuple)
        payload_symbols.append(
            {
                "symbol": symbol,
                "strategy_version": PARAMETERS_VERSION,
                "trades": symbol_trades,
                "pnl": symbol_pnl,
                "stats": [asdict(item) for item in build_exit_path_stats(paths_tuple)],
                "paths": [asdict(item) for item in paths_tuple],
            }
        )
        all_paths.extend(paths_tuple)
        combined_pnl += symbol_pnl
        combined_trades += symbol_trades

    print()
    print("COMBINED BREAKOUT RETEST EXIT PATH")
    print("==================================")
    print(f"symbols : {','.join(args.symbols)}")
    print(f"trades  : {combined_trades}")
    print(f"pnl     : {combined_pnl}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"breakout_retest_exit_path_{stamp}.json"
    csv_path = output_dir / f"breakout_retest_exit_path_{stamp}.csv"
    json_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(timezone.utc),
                    "strategy_version": PARAMETERS_VERSION,
                    "symbols": args.symbols,
                    "interval": args.interval,
                    "start": start,
                    "end": end,
                    "horizons_hours": HORIZONS_HOURS,
                    "strategy_changes": False,
                },
                "summary": {"trades": combined_trades, "pnl": combined_pnl},
                "symbols": payload_symbols,
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )

    rows = [_flatten_csv(item) for item in all_paths]
    if rows:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    print(f"json_artifact: {json_path}")
    print(f"csv_artifact : {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
