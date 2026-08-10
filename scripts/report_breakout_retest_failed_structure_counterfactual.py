from __future__ import annotations

import argparse
import asyncio
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
from app.strategies.breakout_retest import BreakoutRetestStrategy
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED = {
    "BTCUSDT": (Decimal("-0.1391016840064235879634907285"), 49),
    "ETHUSDT": (Decimal("-3.153621560329388837431488648"), 64),
}
TOL = Decimal("1E-24")


def _jd(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


async def main() -> None:
    p = argparse.ArgumentParser(description="Read-only failed-breakout structure counterfactual v1")
    p.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"], choices=["BTCUSDT", "ETHUSDT"])
    p.add_argument("--exchange", default="bybit")
    p.add_argument("--interval", default="1h")
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--train-days", type=int, default=180)
    p.add_argument("--test-days", type=int, default=60)
    p.add_argument("--step-days", type=int, default=60)
    p.add_argument("--initial-balance", type=Decimal, default=Decimal("500"))
    p.add_argument("--seed", type=int, default=42)
    a = p.parse_args()
    if a.interval != "1h":
        raise ValueError("Frozen structural counterfactual supports only 1h")

    start, end = parse_datetime(a.start), parse_datetime(a.end)
    cfg = WalkForwardConfig(
        train_days=a.train_days,
        test_days=a.test_days,
        step_days=a.step_days,
        initial_balance=a.initial_balance,
        random_seed=a.seed,
    )
    windows = generate_walk_forward_windows(start, end, cfg)

    summaries = []
    actual_total = Decimal("0")
    cf_total = Decimal("0")
    triggered = sacrificed = saved = 0
    actual_profitable = cf_profitable = 0

    for symbol in a.symbols:
        candles = await load_candles(a.exchange, symbol, a.interval, start, end)
        agg = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=a.interval,
            start=start,
            end=end,
            config=cfg,
            strategy_factory=lambda s: BreakoutRetestStrategy([s]),
        )
        expected_pnl, expected_trades = EXPECTED[symbol]
        if abs(agg.total_oos_pnl - expected_pnl) > TOL or agg.total_oos_trades != expected_trades:
            raise ValueError(f"Frozen reproduction failed for {symbol}")

        trades = []
        by_window = {}
        for window in windows:
            test_candles = [c for c in candles if window.test_start <= c["open_time"] < window.test_end]
            by_window[window.index] = test_candles
            result = BacktestEngine(
                BacktestConfig(initial_balance=cfg.initial_balance, random_seed=cfg.random_seed)
            ).run(
                candles=test_candles,
                strategy=BreakoutRetestStrategy([symbol]),
                indicator_provider=lambda c, i: c["indicators"],
            )
            trades.extend(
                reconstruct_breakout_retest_trades(result, symbol=symbol, window_index=window.index)
            )

        summary = build_failed_structure_counterfactual(
            tuple(trades), candles_by_window=by_window, symbol=symbol, base_seed=a.seed
        )
        print(f"\nFAILED BREAKOUT STRUCTURE COUNTERFACTUAL v1: {symbol}")
        print("=" * (45 + len(symbol)))
        print(f"trades                    : {summary.trades}")
        print(f"triggered                 : {summary.triggered}")
        print(f"actual_pnl                : {summary.actual_pnl}")
        print(f"counterfactual_pnl        : {summary.counterfactual_pnl}")
        print(f"pnl_delta                 : {summary.pnl_delta}")
        print(f"sacrificed_winners        : {summary.sacrificed_winners}")
        print(f"saved_losers              : {summary.saved_losers}")
        print(f"profitable_windows actual : {summary.actual_profitable_windows}")
        print(f"profitable_windows cf     : {summary.counterfactual_profitable_windows}")
        print(f"LOO min delta             : {summary.leave_one_window_out_min_delta}")
        print(f"LOO all positive          : {summary.leave_one_window_out_all_positive}")
        print("WINDOWS")
        for w in summary.by_window:
            print(
                f"w{w['window_index']:02d} trig={w['triggered']} actual={w['actual_pnl']} "
                f"cf={w['counterfactual_pnl']} delta={w['pnl_delta']} "
                f"sacrificed={w['sacrificed_winners']} saved={w['saved_losers']}"
            )

        summaries.append(summary)
        actual_total += summary.actual_pnl
        cf_total += summary.counterfactual_pnl
        triggered += summary.triggered
        sacrificed += summary.sacrificed_winners
        saved += summary.saved_losers
        actual_profitable += summary.actual_profitable_windows
        cf_profitable += summary.counterfactual_profitable_windows

    combined_delta = cf_total - actual_total
    symbol_map = {s.symbol: s for s in summaries}
    gates = {
        "btc_pnl_delta_positive": "BTCUSDT" not in symbol_map or symbol_map["BTCUSDT"].pnl_delta > 0,
        "eth_pnl_delta_positive": "ETHUSDT" not in symbol_map or symbol_map["ETHUSDT"].pnl_delta > 0,
        "combined_pnl_delta_positive": combined_delta > 0,
        "saved_losers_gt_sacrificed_winners": saved > sacrificed,
        "profitable_windows_not_worse": cf_profitable >= actual_profitable,
        "combined_triggered_ge_10": triggered >= 10,
        "each_symbol_leave_one_window_out_positive": all(s.leave_one_window_out_all_positive for s in summaries),
    }

    print("\nCOMBINED FAILED BREAKOUT STRUCTURE COUNTERFACTUAL v1")
    print("==================================================")
    print(f"actual_pnl         : {actual_total}")
    print(f"counterfactual_pnl : {cf_total}")
    print(f"pnl_delta          : {combined_delta}")
    print(f"triggered          : {triggered}")
    print(f"sacrificed_winners : {sacrificed}")
    print(f"saved_losers       : {saved}")
    print(f"profitable_windows : {actual_profitable} -> {cf_profitable}")
    print("GATES")
    for key, value in gates.items():
        print(f"{key:45}: {value}")

    out = Path("artifacts/diagnostics")
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out / f"breakout_retest_failed_structure_counterfactual_v1_{ts}.json"
    path.write_text(
        json.dumps(
            {
                "metadata": {
                    "rule": "24th completed 1h candle: close < EMA20 AND close < EMA50 AND close < breakout_level; execute SELL at N+1 open",
                    "strategy_unchanged": True,
                    "seed": a.seed,
                },
                "actual_pnl": actual_total,
                "counterfactual_pnl": cf_total,
                "pnl_delta": combined_delta,
                "gates": gates,
                "symbols": [asdict(s) for s in summaries],
            },
            indent=2,
            default=_jd,
        ),
        encoding="utf-8",
    )
    print(f"artifact           : {path}")


if __name__ == "__main__":
    asyncio.run(main())
