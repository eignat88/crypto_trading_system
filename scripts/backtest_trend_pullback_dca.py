#!/usr/bin/env python3
"""Backtest Trend Pullback DCA v1 strategy.

Usage:
    python scripts/backtest_trend_pullback_dca.py
    python scripts/backtest_trend_pullback_dca.py --balance 10000
    python scripts/backtest_trend_pullback_dca.py --min-score 6
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def run_backtest(
    balance: Decimal,
    min_score: int,
    symbols: list[str],
) -> None:
    """Run backtest with Trend Pullback DCA v1."""
    import asyncpg
    from app.config.settings import Settings
    from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
    from app.strategies.trend_pullback_dca import TrendPullbackDCAConfig, TrendPullbackDCAStrategy
    from app.indicators.market_regime import MarketRegime

    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url_sync, min_size=1, max_size=2)

    # Load candles from database
    async def load_candles(symbol: str) -> list[dict]:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT c.open_time, c.close_time, c.open_price, c.high_price,
                       c.low_price, c.close_price, c.volume
                FROM dds.candle c
                JOIN dds.instrument i USING (instrument_id)
                WHERE i.symbol = $1 AND c.interval_code = '1h' AND c.is_valid = true
                ORDER BY c.open_time
            """, symbol)
            return [
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

    print("=" * 60)
    print("BACKTEST: Trend Pullback DCA v1")
    print("=" * 60)
    print(f"Balance: {balance} USDT")
    print(f"Min score: {min_score}/10")
    print(f"Symbols: {', '.join(symbols)}")
    print()

    for symbol in symbols:
        candles = await load_candles(symbol)
        if not candles:
            print(f"  {symbol}: No candles found")
            continue

        print(f"\n{symbol}: {len(candles)} candles")

        # Create strategy with custom config
        config = TrendPullbackDCAConfig(min_score=min_score)
        strategy = TrendPullbackDCAStrategy([symbol], config=config)

        # Create backtest engine
        bt_config = BacktestConfig(
            initial_balance=balance,
            commission_config=None,
            slippage_config=None,
        )
        engine = BacktestEngine(config=bt_config)

        def indicator_provider(candle: dict, index: int) -> dict:
            # Calculate indicators for this candle
            window = candles[max(0, index - 200):index + 1]
            if len(window) < 200:
                return {}
            closes = [Decimal(str(c["close"])) for c in window]

            # EMA
            ema20 = sum(closes[-20:]) / Decimal("20")
            ema50 = sum(closes[-50:]) / Decimal("50")
            ema200 = sum(closes[-200:]) / Decimal("200")

            # RSI (simplified)
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

            # ATR (simplified)
            highs = [Decimal(str(c["high"])) for c in window[-14:]]
            lows = [Decimal(str(c["low"])) for c in window[-14:]]
            atr = (sum(h - l for h, l in zip(highs, lows)) / Decimal("14"))

            # Volatility
            volatility = atr / closes[-1] if closes[-1] > 0 else Decimal("0")

            return {
                "ema_20": ema20,
                "ema_50": ema50,
                "ema_200": ema200,
                "rsi": rsi,
                "atr": atr,
                "volatility": volatility,
                "regime": MarketRegime.TREND_UP if ema50 > ema200 and closes[-1] > ema200 else MarketRegime.RANGE,
            }

        # Run backtest
        result = engine.run(candles, strategy, indicator_provider=indicator_provider)

        # Print results
        print(f"\n  Results:")
        print(f"    Total trades: {result.total_trades}")
        print(f"    Winning trades: {result.winning_trades}")
        print(f"    Losing trades: {result.losing_trades}")
        print(f"    Win rate: {result.win_rate:.1%}")
        print(f"    Total PnL: {result.total_pnl:.2f} USDT")
        print(f"    Max drawdown: {result.max_drawdown:.2%}")
        print(f"    Sharpe ratio: {result.sharpe_ratio or 'N/A'}")
        print(f"    Profit factor: {result.profit_factor:.2f}")
        print(f"    Signals generated: {len(result.signals)}")

        # Save report
        report = {
            "symbol": symbol,
            "strategy": "TrendPullbackDCA_v1",
            "balance": str(balance),
            "min_score": min_score,
            "candles": len(candles),
            "total_trades": result.total_trades,
            "winning_trades": result.winning_trades,
            "losing_trades": result.losing_trades,
            "win_rate": float(result.win_rate),
            "total_pnl": str(result.total_pnl),
            "max_drawdown": str(result.max_drawdown),
            "signals": len(result.signals),
        }
        report_path = PROJECT_ROOT / "artifacts" / f"backtest_{symbol.lower()}_trend_pullback_dca.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"    Report saved: {report_path}")

    await pool.close()
    print("\n" + "=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--balance", type=Decimal, default=Decimal("5000"))
    parser.add_argument("--min-score", type=int, default=7)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    args = parser.parse_args()

    asyncio.run(run_backtest(args.balance, args.min_score, args.symbols))


if __name__ == "__main__":
    main()
