from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.backtest.walk_forward import (
    WalkForwardConfig,
    generate_walk_forward_windows,
    run_fixed_parameter_walk_forward,
)
from app.reporting.breakout_retest_attribution import (
    BreakoutRetestTrade,
    build_breakout_retest_attribution,
    reconstruct_breakout_retest_trades,
)
from app.strategies.breakout_retest import PARAMETERS_VERSION, BreakoutRetestStrategy
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED = {
    "BTCUSDT": {
        "pnl": Decimal("-0.1391016840064235879634907285"),
        "trades": 49,
    },
    "ETHUSDT": {
        "pnl": Decimal("-3.153621560329388837431488648"),
        "trades": 64,
    },
}
PNL_TOLERANCE = Decimal("1E-24")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _validate_reproduction(symbol: str, result) -> None:
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


def _print_buckets(title: str, buckets) -> None:
    print(title)
    print("-" * len(title))
    for item in buckets:
        print(
            f"{item.key:34} trades={item.trades:3d} wins={item.wins:3d} "
            f"losses={item.losses:3d} pnl={item.pnl} "
            f"win_rate={item.win_rate} pf={item.profit_factor}"
        )
    print()


def _print_feature_stats(attribution) -> None:
    print("FEATURE DISTRIBUTIONS (DESCRIPTIVE ONLY)")
    print("----------------------------------------")
    for feature in (
        "breakout_strength_pct",
        "bars_to_retest",
        "retest_depth_pct",
        "retest_close_offset_pct",
        "holding_bars",
        "entry_volatility",
    ):
        print(feature)
        for item in attribution.feature_stats:
            if item.feature != feature or item.outcome not in {"WINNER", "LOSER", "ALL"}:
                continue
            print(
                f"  {item.outcome:6} n={item.count:3d} mean={item.mean} "
                f"median={item.median} p25={item.p25} p75={item.p75}"
            )
    print()


def _trade_row(trade: BreakoutRetestTrade) -> dict[str, Any]:
    return asdict(trade) | {"outcome": trade.outcome}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only attribution for frozen Breakout Retest v1 OOS trades"
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
        raise ValueError("Breakout Retest v1 frozen attribution supports only 1h")

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

    all_trades: list[BreakoutRetestTrade] = []
    payload_symbols: list[dict[str, Any]] = []

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

        symbol_trades: list[BreakoutRetestTrade] = []
        window_payload: list[dict[str, Any]] = []
        for window in windows:
            test_candles = [
                candle
                for candle in candles
                if window.test_start <= candle["open_time"] < window.test_end
            ]
            strategy = BreakoutRetestStrategy([symbol])
            engine = BacktestEngine(
                BacktestConfig(
                    initial_balance=config.initial_balance,
                    random_seed=config.random_seed,
                )
            )
            result = engine.run(
                candles=test_candles,
                strategy=strategy,
                indicator_provider=lambda candle, index: candle["indicators"],
            )
            reconstructed = reconstruct_breakout_retest_trades(
                result,
                symbol=symbol,
                window_index=window.index,
            )
            symbol_trades.extend(reconstructed)
            window_payload.append(
                {
                    "window": asdict(window),
                    "total_pnl": result.total_pnl,
                    "total_trades": result.total_trades,
                    "trades": [_trade_row(trade) for trade in reconstructed],
                }
            )

        symbol_pnl = sum((trade.realized_pnl for trade in symbol_trades), Decimal("0"))
        if len(symbol_trades) != aggregate.total_oos_trades:
            raise ValueError(
                f"Cross-window trade reconciliation failed for {symbol}: "
                f"aggregate={aggregate.total_oos_trades} reconstructed={len(symbol_trades)}"
            )
        if abs(symbol_pnl - aggregate.total_oos_pnl) > PNL_TOLERANCE:
            raise ValueError(
                f"Cross-window PnL reconciliation failed for {symbol}: "
                f"aggregate={aggregate.total_oos_pnl} reconstructed={symbol_pnl}"
            )

        attribution = build_breakout_retest_attribution(tuple(symbol_trades), symbol=symbol)
        all_trades.extend(symbol_trades)

        print()
        print(f"BREAKOUT RETEST ATTRIBUTION: {symbol}")
        print("=" * (29 + len(symbol)))
        print(f"strategy_version : {PARAMETERS_VERSION}")
        print(f"trades           : {attribution.total_trades}")
        print(f"pnl              : {attribution.total_pnl}")
        print()
        _print_buckets("BY EXIT REASON", attribution.by_exit_reason)
        _print_buckets("BY ENTRY REGIME", attribution.by_entry_regime)
        _print_buckets("BY WINDOW", attribution.by_window)
        _print_feature_stats(attribution)

        payload_symbols.append(
            {
                "symbol": symbol,
                "summary": {
                    "total_trades": attribution.total_trades,
                    "total_pnl": attribution.total_pnl,
                },
                "by_exit_reason": [asdict(item) for item in attribution.by_exit_reason],
                "by_entry_regime": [asdict(item) for item in attribution.by_entry_regime],
                "by_window": [asdict(item) for item in attribution.by_window],
                "by_outcome": [asdict(item) for item in attribution.by_outcome],
                "feature_stats": [asdict(item) for item in attribution.feature_stats],
                "windows": window_payload,
            }
        )

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_artifact = output_dir / f"breakout_retest_attribution_{timestamp}.json"
    csv_artifact = output_dir / f"breakout_retest_attribution_{timestamp}.csv"

    json_artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(UTC),
                    "strategy_version": PARAMETERS_VERSION,
                    "exchange": args.exchange,
                    "symbols": args.symbols,
                    "interval": args.interval,
                    "start": start,
                    "end": end,
                    "walk_forward_config": asdict(config),
                    "parameter_optimization": False,
                    "read_only_diagnostic": True,
                },
                "summary": {
                    "total_trades": len(all_trades),
                    "total_pnl": sum(
                        (trade.realized_pnl for trade in all_trades), Decimal("0")
                    ),
                },
                "symbols": payload_symbols,
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )

    rows = [_trade_row(trade) for trade in all_trades]
    if rows:
        with csv_artifact.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _json_default(value) if isinstance(value, (Decimal, datetime)) else value for key, value in row.items()})
    else:
        csv_artifact.write_text("", encoding="utf-8")

    print("COMBINED BREAKOUT RETEST ATTRIBUTION")
    print("====================================")
    print(f"symbols       : {','.join(args.symbols)}")
    print(f"trades        : {len(all_trades)}")
    print(
        "pnl           : "
        f"{sum((trade.realized_pnl for trade in all_trades), Decimal('0'))}"
    )
    print(f"json_artifact : {json_artifact}")
    print(f"csv_artifact  : {csv_artifact}")


if __name__ == "__main__":
    asyncio.run(main())
