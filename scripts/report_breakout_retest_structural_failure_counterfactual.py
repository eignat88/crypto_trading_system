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
from app.backtest.walk_forward import (
    WalkForwardConfig,
    generate_walk_forward_windows,
    run_fixed_parameter_walk_forward,
)
from app.reporting.breakout_retest_attribution import reconstruct_breakout_retest_trades
from app.reporting.breakout_retest_structural_failure_counterfactual import (
    RULE_NAME,
    build_structural_failure_counterfactual,
)
from app.strategies.breakout_retest import BreakoutRetestStrategy
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED = {
    "BTCUSDT": (Decimal("-0.1391016840064235879634907285"), 49),
    "ETHUSDT": (Decimal("-3.153621560329388837431488648"), 64),
}
TOLERANCE = Decimal("1E-24")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _decision_gates(summaries: list[Any]) -> dict[str, bool]:
    by_symbol = {summary.symbol: summary for summary in summaries}
    btc = by_symbol.get("BTCUSDT")
    eth = by_symbol.get("ETHUSDT")
    actual_total = sum((item.actual_pnl for item in summaries), Decimal("0"))
    cf_total = sum((item.counterfactual_pnl for item in summaries), Decimal("0"))
    saved_td = sum(item.saved_trend_down_losses for item in summaries)
    sacrificed = sum(item.sacrificed_winners for item in summaries)

    return {
        "btc_pnl_improved": btc is not None and btc.counterfactual_pnl > btc.actual_pnl,
        "eth_pnl_improved": eth is not None and eth.counterfactual_pnl > eth.actual_pnl,
        "combined_pnl_improved": cf_total > actual_total,
        "combined_pnl_positive": cf_total > 0,
        "saved_td_losses_gt_sacrificed_winners": saved_td > sacrificed,
        "not_single_symbol_dependent": (
            btc is not None
            and eth is not None
            and btc.pnl_delta > 0
            and eth.pnl_delta > 0
        ),
        "at_least_two_positive_windows_per_symbol": all(
            item.positive_delta_windows >= 2 for item in summaries
        ),
        "technical_integrity": True,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Frozen read-only Breakout Structural Failure Counterfactual v1"
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
        raise ValueError("Frozen structural-failure counterfactual supports only 1h")

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

    summaries = []
    for symbol in args.symbols:
        candles = await load_candles(
            args.exchange,
            symbol,
            args.interval,
            start,
            end,
        )
        aggregate = run_fixed_parameter_walk_forward(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
            strategy_factory=lambda current_symbol: BreakoutRetestStrategy([current_symbol]),
        )
        expected_pnl, expected_trades = EXPECTED[symbol]
        if (
            abs(aggregate.total_oos_pnl - expected_pnl) > TOLERANCE
            or aggregate.total_oos_trades != expected_trades
        ):
            raise ValueError(
                f"Frozen Breakout Retest reproduction failed for {symbol}: "
                f"pnl={aggregate.total_oos_pnl} trades={aggregate.total_oos_trades}"
            )

        trades = []
        candles_by_window: dict[int, list[dict[str, Any]]] = {}
        for window in windows:
            test_candles = [
                candle
                for candle in candles
                if window.test_start <= candle["open_time"] < window.test_end
            ]
            candles_by_window[window.index] = test_candles
            result = BacktestEngine(
                BacktestConfig(
                    initial_balance=config.initial_balance,
                    random_seed=config.random_seed,
                )
            ).run(
                candles=test_candles,
                strategy=BreakoutRetestStrategy([symbol]),
                indicator_provider=lambda candle, index: candle["indicators"],
            )
            trades.extend(
                reconstruct_breakout_retest_trades(
                    result,
                    symbol=symbol,
                    window_index=window.index,
                )
            )

        reconstructed_pnl = sum((trade.realized_pnl for trade in trades), Decimal("0"))
        if len(trades) != aggregate.total_oos_trades:
            raise ValueError(
                f"Cross-window trade reconciliation failed for {symbol}: "
                f"aggregate={aggregate.total_oos_trades} reconstructed={len(trades)}"
            )
        if abs(reconstructed_pnl - aggregate.total_oos_pnl) > TOLERANCE:
            raise ValueError(
                f"Cross-window PnL reconciliation failed for {symbol}: "
                f"aggregate={aggregate.total_oos_pnl} reconstructed={reconstructed_pnl}"
            )

        summary = build_structural_failure_counterfactual(
            tuple(trades),
            candles_by_window=candles_by_window,
            symbol=symbol,
            base_seed=args.seed,
        )
        summaries.append(summary)

        print(f"\nBREAKOUT STRUCTURAL FAILURE COUNTERFACTUAL v1: {symbol}")
        print("=" * (45 + len(symbol)))
        print("rule                  : 24h + close < breakout_level + close < EMA20 + EMA20 falling")
        print(f"trades                : {summary.trades}")
        print(f"triggered             : {summary.triggered}")
        print(f"actual_pnl            : {summary.actual_pnl}")
        print(f"counterfactual_pnl    : {summary.counterfactual_pnl}")
        print(f"pnl_delta             : {summary.pnl_delta}")
        print(f"actual_winners        : {summary.actual_winners}")
        print(f"counterfactual_winners: {summary.counterfactual_winners}")
        print(f"sacrificed_winners    : {summary.sacrificed_winners}")
        print(f"saved_losers          : {summary.saved_losers}")
        print(f"saved_td_losses       : {summary.saved_trend_down_losses}")
        print(f"triggered_td_losses   : {summary.triggered_trend_down_losses}")
        print(f"triggered_max_hold    : {summary.triggered_max_holding_losses}")
        print(f"positive_delta_windows: {summary.positive_delta_windows}")
        print("WINDOWS")
        for item in summary.by_window:
            print(
                f"w{item['window_index']:02d} trig={item['triggered']} "
                f"actual={item['actual_pnl']} cf={item['counterfactual_pnl']} "
                f"delta={item['pnl_delta']} sacrificed={item['sacrificed_winners']} "
                f"saved={item['saved_losers']} saved_td={item['saved_trend_down_losses']}"
            )

    actual_total = sum((item.actual_pnl for item in summaries), Decimal("0"))
    cf_total = sum((item.counterfactual_pnl for item in summaries), Decimal("0"))
    gates = _decision_gates(summaries)
    decision = "PROMISING_REQUIRES_INDEPENDENT_VALIDATION" if all(gates.values()) else "REJECTED"

    print("\nCOMBINED BREAKOUT STRUCTURAL FAILURE COUNTERFACTUAL v1")
    print("=====================================================")
    print(f"actual_pnl         : {actual_total}")
    print(f"counterfactual_pnl : {cf_total}")
    print(f"pnl_delta          : {cf_total - actual_total}")
    print(f"triggered          : {sum(item.triggered for item in summaries)}")
    print(f"sacrificed_winners : {sum(item.sacrificed_winners for item in summaries)}")
    print(f"saved_losers       : {sum(item.saved_losers for item in summaries)}")
    print(f"saved_td_losses    : {sum(item.saved_trend_down_losses for item in summaries)}")
    print("GATES")
    for name, passed in gates.items():
        print(f"{name:42}: {passed}")
    print(f"decision           : {decision}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"breakout_structural_failure_counterfactual_v1_{timestamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "rule_name": RULE_NAME,
                    "frozen_spec": "docs/breakout_structural_failure_counterfactual_v1.md",
                    "rule": "24h close < breakout_level AND close < EMA20 AND EMA20 < previous EMA20; execute N+1 open",
                    "seed": args.seed,
                    "viewed_oos_warning": True,
                },
                "actual_pnl": actual_total,
                "counterfactual_pnl": cf_total,
                "pnl_delta": cf_total - actual_total,
                "gates": gates,
                "decision": decision,
                "symbols": [asdict(summary) for summary in summaries],
            },
            indent=2,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print(f"artifact           : {artifact}")


if __name__ == "__main__":
    asyncio.run(main())
