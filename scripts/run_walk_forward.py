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
from run_backtest import load_candles, parse_datetime


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fixed-parameter TrendDCA walk-forward baseline"
    )
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--symbol", required=True, choices=["BTCUSDT", "ETHUSDT"])
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

    candles = await load_candles(
        exchange=args.exchange,
        symbol=args.symbol,
        interval=args.interval,
        start=start,
        end=end,
    )

    result = run_fixed_parameter_walk_forward(
        candles=candles,
        symbol=args.symbol,
        interval=args.interval,
        start=start,
        end=end,
        config=config,
    )

    payload = {
        "metadata": {
            "created_at": datetime.now(timezone.utc),
            "exchange": args.exchange,
            "symbol": args.symbol,
            "interval": args.interval,
            "start": start,
            "end": end,
        },
        "configuration": asdict(config),
        "summary": {
            "windows": len(result.windows),
            "total_oos_pnl": result.total_oos_pnl,
            "profitable_windows": result.profitable_windows,
            "losing_windows": result.losing_windows,
            "flat_windows": result.flat_windows,
            "profitable_window_rate": result.profitable_window_rate,
            "total_oos_trades": result.total_oos_trades,
        },
        "windows": [
            {
                "index": item.window.index,
                "train_start": item.window.train_start,
                "train_end": item.window.train_end,
                "test_start": item.window.test_start,
                "test_end": item.window.test_end,
                "candle_count": item.candle_count,
                "initial_balance": item.initial_balance,
                "final_equity": item.final_equity,
                "total_pnl": item.total_pnl,
                "return_pct": item.return_pct,
                "total_trades": item.total_trades,
                "winning_trades": item.winning_trades,
                "losing_trades": item.losing_trades,
                "win_rate": item.win_rate,
                "profit_factor": item.profit_factor,
                "max_drawdown": item.max_drawdown,
            }
            for item in result.windows
        ],
    }

    output_dir = Path("artifacts/walk_forward")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_file = output_dir / f"trend_dca_{args.symbol}_{args.interval}_{timestamp}.json"
    output_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default),
        encoding="utf-8",
    )

    print()
    print("WALK-FORWARD COMPLETED")
    print("----------------------")
    print(f"symbol                  : {result.symbol}")
    print(f"interval                : {result.interval}")
    print(f"train_days              : {config.train_days}")
    print(f"test_days               : {config.test_days}")
    print(f"step_days               : {config.step_days}")
    print(f"windows                 : {len(result.windows)}")
    print(f"total_oos_pnl           : {result.total_oos_pnl}")
    print(f"profitable_windows      : {result.profitable_windows}")
    print(f"losing_windows          : {result.losing_windows}")
    print(f"flat_windows            : {result.flat_windows}")
    print(f"profitable_window_rate  : {result.profitable_window_rate}")
    print(f"total_oos_trades        : {result.total_oos_trades}")
    print(f"artifact                : {output_file}")
    print()
    print("WINDOWS")
    print("-------")
    for item in result.windows:
        print(
            f"{item.window.index:02d} "
            f"train={item.window.train_start.date()}..{item.window.train_end.date()} "
            f"test={item.window.test_start.date()}..{item.window.test_end.date()} "
            f"candles={item.candle_count} trades={item.total_trades} "
            f"pnl={item.total_pnl} pf={item.profit_factor} "
            f"dd={item.max_drawdown}"
        )


if __name__ == "__main__":
    asyncio.run(main())
