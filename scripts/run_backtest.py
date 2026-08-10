from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.database.connection import async_session_factory
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy


def parse_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    result = datetime.fromisoformat(normalized)

    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)

    return result.astimezone(timezone.utc)


def json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    return str(value)


def serialize_object(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)

    if hasattr(value, "__dict__"):
        return dict(value.__dict__)

    return str(value)


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


async def load_candles(
    exchange: str,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT
            c.candle_id,
            i.symbol,
            c.interval_code,
            c.open_time,
            c.open_price AS open,
            c.high_price AS high,
            c.low_price AS low,
            c.close_price AS close,
            c.volume,

            ema20.indicator_value AS ema_20,
            ema50.indicator_value AS ema_50,
            ema200.indicator_value AS ema_200,
            rsi14.indicator_value AS rsi,
            atr14.indicator_value AS atr,
            vol20.indicator_value AS volatility,

            mr.regime,
            mr.confidence AS regime_confidence

        FROM dds.candle c

        JOIN dds.instrument i
          ON i.instrument_id = c.instrument_id

        LEFT JOIN dds.indicator ema20
          ON ema20.candle_id = c.candle_id
         AND ema20.indicator_name = 'EMA'
         AND ema20.indicator_params = '{"period": 20}'::jsonb

        LEFT JOIN dds.indicator ema50
          ON ema50.candle_id = c.candle_id
         AND ema50.indicator_name = 'EMA'
         AND ema50.indicator_params = '{"period": 50}'::jsonb

        LEFT JOIN dds.indicator ema200
          ON ema200.candle_id = c.candle_id
         AND ema200.indicator_name = 'EMA'
         AND ema200.indicator_params = '{"period": 200}'::jsonb

        LEFT JOIN dds.indicator rsi14
          ON rsi14.candle_id = c.candle_id
         AND rsi14.indicator_name = 'RSI'
         AND rsi14.indicator_params = '{"period": 14}'::jsonb

        LEFT JOIN dds.indicator atr14
          ON atr14.candle_id = c.candle_id
         AND atr14.indicator_name = 'ATR'
         AND atr14.indicator_params = '{"period": 14}'::jsonb

        LEFT JOIN dds.indicator vol20
          ON vol20.candle_id = c.candle_id
         AND vol20.indicator_name = 'VOLATILITY'
         AND vol20.indicator_params = '{"period": 20}'::jsonb

        LEFT JOIN dds.market_regime mr
          ON mr.candle_id = c.candle_id

        WHERE i.exchange_name = :exchange
          AND i.symbol = :symbol
          AND c.interval_code = :interval
          AND c.open_time >= :start
          AND c.open_time < :end
          AND c.is_valid = true

        ORDER BY c.open_time ASC
        """
    )

    async with async_session_factory() as session:
        result = await session.execute(
            query,
            {
                "exchange": exchange,
                "symbol": symbol,
                "interval": interval,
                "start": start,
                "end": end,
            },
        )

        rows = [dict(row._mapping) for row in result.fetchall()]

    candles: list[dict[str, Any]] = []

    for row in rows:
        candles.append(
            {
                "candle_id": row["candle_id"],
                "symbol": row["symbol"],
                "interval": row["interval_code"],
                "open_time": row["open_time"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "indicators": {
                    "ema_20": row["ema_20"],
                    "ema_50": row["ema_50"],
                    "ema_200": row["ema_200"],
                    "rsi": row["rsi"],
                    "atr": row["atr"],
                    "volatility": row["volatility"],
                    "regime": row["regime"],
                    "regime_confidence": row["regime_confidence"],
                },
            }
        )

    return candles


def validate_candles(
    candles: list[dict[str, Any]],
    interval: str,
    start: datetime,
    end: datetime,
) -> None:
    if not candles:
        raise RuntimeError("No DDS candles found for requested backtest range")

    interval_seconds = {
        "5m": 5 * 60,
        "15m": 15 * 60,
        "1h": 60 * 60,
        "4h": 4 * 60 * 60,
        "1d": 24 * 60 * 60,
    }

    if interval not in interval_seconds:
        raise RuntimeError(f"Unsupported interval: {interval}")

    step = interval_seconds[interval]
    expected = int((end - start).total_seconds() / step)

    if len(candles) != expected:
        raise RuntimeError(
            f"Backtest data is incomplete: expected={expected}, actual={len(candles)}"
        )

    for previous, current in zip(candles, candles[1:]):
        delta = (
            current["open_time"] - previous["open_time"]
        ).total_seconds()

        if delta != step:
            raise RuntimeError(
                "Backtest data contains time gap: "
                f"{previous['open_time']} -> {current['open_time']}"
            )


def build_output(
    result: Any,
    args: argparse.Namespace,
    candles: list[dict[str, Any]],
) -> dict[str, Any]:
    final_equity = result.portfolio.total_equity

    return {
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": git_commit(),
            "exchange": args.exchange,
            "symbol": args.symbol,
            "interval": args.interval,
            "start": args.start,
            "end": args.end,
            "candle_count": len(candles),
            "random_seed": args.seed,
        },
        "strategy": {
            "name": "TrendDCA",
            "parameters": asdict(DCAConfig()),
        },
        "backtest": {
            "initial_balance": args.initial_balance,
            "final_equity": final_equity,
            "total_pnl": result.total_pnl,
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": result.win_rate,
            "profit_factor": result.profit_factor,
            "average_trade": result.average_trade,
            "average_win": result.average_win,
            "average_loss": result.average_loss,
            "max_drawdown": result.max_drawdown,
            "max_consecutive_losses": result.max_consecutive_losses,
        },
        "audit": {
            "signals": [
                serialize_object(item)
                for item in result.signals
            ],
            "risk_decisions": [
                serialize_object(item)
                for item in result.risk_decisions
            ],
            "orders": [
                serialize_object(item)
                for item in result.orders
            ],
            "fills": [
                serialize_object(item)
                for item in result.fills
            ],
        },
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run reproducible TrendDCA backtest on DDS candles"
    )

    parser.add_argument("--exchange", default="bybit")
    parser.add_argument(
        "--symbol",
        required=True,
        choices=["BTCUSDT", "ETHUSDT"],
    )
    parser.add_argument(
        "--interval",
        required=True,
        choices=["5m", "15m", "1h", "4h", "1d"],
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)

    parser.add_argument(
        "--initial-balance",
        default="500",
        help="Initial quote-currency balance",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )

    args = parser.parse_args()

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)

    if end <= start:
        raise RuntimeError("--end must be greater than --start")

    candles = await load_candles(
        exchange=args.exchange,
        symbol=args.symbol,
        interval=args.interval,
        start=start,
        end=end,
    )

    validate_candles(
        candles=candles,
        interval=args.interval,
        start=start,
        end=end,
    )

    strategy = TrendDCAStrategy(
        symbols=[args.symbol],
    )

    config = BacktestConfig(
        initial_balance=Decimal(args.initial_balance),
        random_seed=args.seed,
    )

    engine = BacktestEngine(config=config)

    result = engine.run(
        candles=candles,
        strategy=strategy,
        indicator_provider=lambda candle, index: candle["indicators"],
    )

    payload = build_output(
        result=result,
        args=args,
        candles=candles,
    )

    output_dir = Path("artifacts/backtests")
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    output_file = output_dir / (
        f"trend_dca_{args.symbol}_{args.interval}_{timestamp}.json"
    )

    output_file.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
            default=json_default,
        ),
        encoding="utf-8",
    )

    print()
    print("BACKTEST COMPLETED")
    print("------------------")
    print(f"symbol             : {args.symbol}")
    print(f"interval           : {args.interval}")
    print(f"candles            : {len(candles)}")
    print(f"initial_balance    : {args.initial_balance}")
    print(f"final_equity       : {result.portfolio.total_equity}")
    print(f"total_pnl          : {result.total_pnl}")
    print(f"total_trades       : {result.total_trades}")
    print(f"winning_trades     : {result.winning_trades}")
    print(f"losing_trades      : {result.losing_trades}")
    print(f"win_rate           : {result.win_rate}")
    print(f"profit_factor      : {result.profit_factor}")
    print(f"max_drawdown       : {result.max_drawdown}")
    print(f"signals            : {len(result.signals)}")
    print(f"risk_decisions     : {len(result.risk_decisions)}")
    print(f"orders             : {len(result.orders)}")
    print(f"fills              : {len(result.fills)}")
    print(f"audit_file         : {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
