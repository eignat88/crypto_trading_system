#!/usr/bin/env python3
"""Backtest PEPE Scalper strategy on 15m candles.

Usage:
    python scripts/backtest_pepe_scalper.py
    python scripts/backtest_pepe_scalper.py --balance 1000
"""

from __future__ import annotations

import argparse
import asyncio
import httpx
import json
import sys
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def load_15m_candles(symbol: str, days: int = 30) -> list[dict]:
    """Load 15m candles from Bybit API."""
    async with httpx.AsyncClient() as client:
        end_time = int(datetime.now(UTC).timestamp() * 1000)
        start_time = int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)

        response = await client.get(
            'https://api-demo.bybit.com/v5/market/kline',
            params={
                'category': 'spot',
                'symbol': symbol,
                'interval': '15',
                'start': start_time,
                'end': end_time,
                'limit': 1000,
            }
        )
        data = response.json()

        if data['retCode'] != 0:
            raise Exception(f"API error: {data['retMsg']}")

        candles = []
        for row in reversed(data['result']['list']):
            candles.append({
                'symbol': symbol,
                'open_time': datetime.fromtimestamp(int(row[0]) / 1000, UTC),
                'open': Decimal(row[1]),
                'high': Decimal(row[2]),
                'low': Decimal(row[3]),
                'close': Decimal(row[4]),
                'volume': Decimal(row[5]),
            })

        return candles


async def run_backtest(balance: Decimal, symbol: str) -> None:
    """Run backtest with PEPE Scalper strategy."""
    from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
    from app.strategies.pepe_scalper import PEPEScalperConfig, PEPEScalperStrategy
    from app.indicators.market_regime import MarketRegime

    print("=" * 60)
    print(f"BACKTEST: PEPE Scalper — {symbol} (15m)")
    print("=" * 60)

    # Load candles
    print("Loading 15m candles...")
    candles = await load_15m_candles(symbol, days=30)
    print(f"Loaded {len(candles)} candles ({len(candles) * 15 / 60 / 24:.1f} days)")
    print(f"Period: {candles[0]['open_time']} → {candles[-1]['open_time']}")
    print()

    # Create strategy
    config = PEPEScalperConfig()
    strategy = PEPEScalperStrategy([symbol], config=config)

    # Create backtest engine
    bt_config = BacktestConfig(initial_balance=balance)
    engine = BacktestEngine(config=bt_config)

    # Indicator provider
    def indicator_provider(candle: dict, index: int) -> dict:
        window = candles[max(0, index - 100):index + 1]
        if len(window) < 20:
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
        "strategy": "PEPEScalper_v1",
        "symbol": symbol,
        "timeframe": "15m",
        "balance": str(balance),
        "candles": len(candles),
        "period_days": len(candles) * 15 / 60 / 24,
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
    report_path = PROJECT_ROOT / "artifacts" / f"backtest_{symbol.lower()}_pepe_scalper.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved: {report_path}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--balance", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--symbol", default="PEPEUSDT")
    args = parser.parse_args()

    asyncio.run(run_backtest(args.balance, args.symbol))


if __name__ == "__main__":
    main()
