#!/usr/bin/env python3
"""Backtest Momentum Crossover strategy.

Usage:
    python scripts/backtest_momentum.py
    python scripts/backtest_momentum.py --balance 1000
    python scripts/backtest_momentum.py --symbol ETHUSDT
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def run_backtest(balance: Decimal, symbol: str) -> None:
    """Run backtest with Momentum Crossover strategy."""
    import asyncpg
    from app.config.settings import Settings
    from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
    from app.strategies.momentum_crossover import MomentumCrossoverConfig, MomentumCrossoverStrategy
    from app.indicators.market_regime import MarketRegime

    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url_sync, min_size=1, max_size=2)

    # Load candles from database
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.open_time, c.open_price, c.high_price, c.low_price, c.close_price, c.volume
            FROM dds.candle c
            JOIN dds.instrument i USING (instrument_id)
            WHERE i.symbol = $1 AND c.interval_code = '1h' AND c.is_valid = true
            ORDER BY c.open_time
        """, symbol)
        candles = [
            {
                "symbol": symbol,
                "open_time": row["open_time"],
                "open": Decimal(str(row["open_price"])),
                "high": Decimal(str(row["high_price"])),
                "low": Decimal(str(row["low_price"])),
                "close": Decimal(str(row["close_price"])),
                "volume": Decimal(str(row["volume"])),
            }
            for row in rows
        ]

    await pool.close()

    print("=" * 60)
    print(f"BACKTEST: Momentum Crossover — {symbol}")
    print("=" * 60)
    print(f"Balance: {balance} USDT")
    print(f"Candles: {len(candles)}")
    print(f"Period: {candles[0]['open_time']} → {candles[-1]['open_time']}")
    print()

    # Create strategy
    config = MomentumCrossoverConfig()
    strategy = MomentumCrossoverStrategy([symbol], config=config)

    # Create backtest engine
    bt_config = BacktestConfig(initial_balance=balance)
    engine = BacktestEngine(config=bt_config)

    # Indicator provider
    def indicator_provider(candle: dict, index: int) -> dict:
        window = candles[max(0, index - 200):index + 1]
        if len(window) < 50:
            return {}
        closes = [Decimal(str(c["close"])) for c in window]

        # EMA
        ema20 = sum(closes[-20:]) / Decimal("20")
        ema50 = sum(closes[-50:]) / Decimal("50") if len(closes) >= 50 else ema20

        # RSI
        gains = []
        losses = []
        for i in range(1, min(15, len(closes))):
            diff = closes[-i] - closes[-i - 1]
            if diff > 0:
                gains.append(diff)
            else:
                losses.append(abs(diff))
        avg_gain = sum(gains) / Decimal("14") if gains else Decimal("0")
        avg_loss = sum(losses) / Decimal("14") if losses else Decimal("0.0001")
        rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + avg_gain / avg_loss))

        # ATR
        highs = [Decimal(str(c["high"])) for c in window[-14:]]
        lows = [Decimal(str(c["low"])) for c in window[-14:]]
        atr = sum(h - l for h, l in zip(highs, lows)) / Decimal("14")

        # Regime
        if ema50 > ema20 and closes[-1] > ema20:
            regime = MarketRegime.TREND_UP
        elif ema50 < ema20 and closes[-1] < ema20:
            regime = MarketRegime.TREND_DOWN
        else:
            regime = MarketRegime.RANGE

        return {
            "ema_20": ema20,
            "ema_50": ema50,
            "rsi": rsi,
            "atr": atr,
            "volatility": atr / closes[-1] if closes[-1] > 0 else Decimal("0"),
            "regime": regime,
        }

    # Run backtest
    result = engine.run(candles, strategy, indicator_provider=indicator_provider)

    # Print results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Total trades: {result.total_trades}")
    print(f"Winning trades: {result.winning_trades}")
    print(f"Losing trades: {result.losing_trades}")
    print(f"Win rate: {result.win_rate:.1%}")
    print(f"Total PnL: {result.total_pnl:.2f} USDT")
    print(f"PnL %: {result.total_pnl / balance * 100:.2f}%")
    print(f"Max drawdown: {result.max_drawdown:.2%}")
    print(f"Profit factor: {result.profit_factor:.2f}")
    print(f"Signals generated: {len(result.signals)}")

    # Save report
    report = {
        "strategy": "MomentumCrossover_v1",
        "symbol": symbol,
        "balance": str(balance),
        "candles": len(candles),
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "win_rate": float(result.win_rate),
        "total_pnl": str(result.total_pnl),
        "pnl_pct": float(result.total_pnl / balance * 100),
        "max_drawdown": str(result.max_drawdown),
        "profit_factor": float(result.profit_factor),
        "signals": len(result.signals),
    }
    report_path = PROJECT_ROOT / "artifacts" / f"backtest_{symbol.lower()}_momentum.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved: {report_path}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--balance", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--symbol", default="BTCUSDT")
    args = parser.parse_args()

    asyncio.run(run_backtest(args.balance, args.symbol))


if __name__ == "__main__":
    main()
