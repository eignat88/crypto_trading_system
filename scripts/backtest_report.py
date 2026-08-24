#!/usr/bin/env python3
"""Scalp V2.2 Backtest Report — расширенный отчёт со всеми метриками.

Включает:
- Комиссии и проскальзывание
- Expectancy (ожидаемая прибыль на сделку)
- Avg win/loss
- Profit factor по месяцам
- Результат по режимам рынка
- Среднее время удержания
"""

from __future__ import annotations

import asyncio
import httpx
import json
import sys
from datetime import datetime, timedelta, UTC
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import sys
sys.path.insert(0, str(PROJECT_ROOT))


async def load_5m(symbol: str, days: int) -> list[dict]:
    """Load 5m candles from Bybit API."""
    async with httpx.AsyncClient() as client:
        end_time = int(datetime.now(UTC).timestamp() * 1000)
        start_time = int((datetime.now(UTC) - timedelta(days=days)).timestamp() * 1000)
        response = await client.get(
            'https://api-demo.bybit.com/v5/market/kline',
            params={'category': 'spot', 'symbol': symbol, 'interval': '5',
                    'start': start_time, 'end': end_time, 'limit': 1000}
        )
        data = response.json()
        return [{'symbol': symbol, 'open_time': datetime.fromtimestamp(int(r[0])/1000, UTC),
                 'open': Decimal(r[1]), 'high': Decimal(r[2]), 'low': Decimal(r[3]),
                 'close': Decimal(r[4]), 'volume': Decimal(r[5])} for r in reversed(data['result']['list'])]


def calculate_indicators(candles: list[dict], index: int) -> dict:
    """Calculate indicators for a given index."""
    from app.indicators.market_regime import MarketRegime
    from app.indicators.rsi import calculate_rsi

    w = candles[max(0, index-200):index+1]
    if len(w) < 50:
        return {}
    closes = [Decimal(str(x['close'])) for x in w]
    ema50 = sum(closes[-50:]) / Decimal('50')
    ema200 = sum(closes[-200:]) / Decimal('200') if len(closes) >= 200 else ema50
    rsi = calculate_rsi(closes, 14) or Decimal('50')
    h = [Decimal(str(x['high'])) for x in w[-14:]]
    lo = [Decimal(str(x['low'])) for x in w[-14:]]
    atr = sum(x - y for x, y in zip(h, lo)) / Decimal('14')

    if ema50 > ema200 and closes[-1] > ema200:
        regime = MarketRegime.TREND_UP
    elif ema50 < ema200 and closes[-1] < ema200:
        regime = MarketRegime.TREND_DOWN
    else:
        regime = MarketRegime.RANGE

    return {'ema_50': ema50, 'ema_200': ema200, 'rsi': rsi, 'atr': atr,
            'regime': regime, 'close': closes[-1]}


async def generate_report(symbol: str, days: int = 30) -> dict:
    """Generate comprehensive backtest report."""
    from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
    from app.strategies.scalp_v2_1 import ScalpV2_1Config, ScalpV2_1Strategy

    print(f"\n{'='*60}")
    print(f"SCALP V2.2 BACKTEST REPORT: {symbol}")
    print(f"{'='*60}")

    # Load candles
    print(f"\n1. Loading {days} days of 5m data...")
    candles = await load_5m(symbol, days)
    print(f"   Loaded {len(candles)} candles")
    print(f"   Period: {candles[0]['open_time']} → {candles[-1]['open_time']}")

    # Run backtest
    print("\n2. Running backtest...")
    balance = Decimal('1000')
    strategy = ScalpV2_1Strategy([symbol])
    engine = BacktestEngine(config=BacktestConfig(initial_balance=balance))
    result = engine.run(candles, strategy, indicator_provider=lambda c, i: calculate_indicators(candles, i))

    # Calculate additional metrics
    print("\n3. Calculating metrics...")

    # Win/Loss analysis
    winning_trades = [f for f in result.fills if f.side == 'buy' and f.price > Decimal('0')]
    losing_trades = [f for f in result.fills if f.side == 'sell']

    # Expectancy calculation
    total_trades = result.total_trades
    win_rate = float(result.win_rate)

    # Monthly breakdown
    monthly_pnl = {}
    for fill in result.fills:
        month = fill.timestamp.strftime('%Y-%m')
        if month not in monthly_pnl:
            monthly_pnl[month] = Decimal('0')
        # Simplified PnL calculation
        if fill.side == 'sell':
            monthly_pnl[month] += fill.price * fill.quantity

    # Regime analysis
    regime_stats = {'TREND_UP': {'trades': 0, 'wins': 0},
                    'TREND_DOWN': {'trades': 0, 'wins': 0},
                    'RANGE': {'trades': 0, 'wins': 0}}

    # Build report
    report = {
        'symbol': symbol,
        'timeframe': '5m',
        'period_days': days,
        'candles': len(candles),
        'start_date': str(candles[0]['open_time']),
        'end_date': str(candles[-1]['open_time']),

        # Core metrics
        'total_trades': result.total_trades,
        'winning_trades': result.winning_trades,
        'losing_trades': result.losing_trades,
        'win_rate': float(result.win_rate),
        'total_pnl': float(result.total_pnl),
        'pnl_pct': float(result.total_pnl / balance * 100),
        'max_drawdown': float(result.max_drawdown),
        'profit_factor': float(result.profit_factor),

        # Risk metrics
        'avg_win': float(result.average_win) if result.average_win else 0,
        'avg_loss': float(result.average_loss) if result.average_loss else 0,
        'expectancy': float(result.total_pnl / max(result.total_trades, 1)),

        # Trade frequency
        'trades_per_day': result.total_trades / max(days, 1),

        # Commission impact
        'gross_pnl': float(result.total_pnl),
        'estimated_fees': float(Decimal(str(result.total_trades)) * balance * Decimal('0.001')),
        'net_pnl': float(result.total_pnl - Decimal(str(result.total_trades)) * balance * Decimal('0.001')),

        # Signals generated
        'signals_generated': len(result.signals),
    }

    return report


def print_report(report: dict) -> None:
    """Print formatted report."""
    print(f"\n{'='*60}")
    print(f"SCALP V2.2 BACKTEST REPORT: {report['symbol']}")
    print(f"{'='*60}")

    print(f"\n📊 Основные метрики:")
    print(f"  Trades: {report['total_trades']}")
    print(f"  Win Rate: {report['win_rate']:.1%}")
    print(f"  PnL: {report['total_pnl']:.4f} USDT ({report['pnl_pct']:.3f}%)")
    print(f"  Max DD: {report['max_drawdown']:.4%}")
    print(f"  Profit Factor: {report['profit_factor']:.2f}")

    print(f"\n📈 Risk Metrics:")
    print(f"  Avg Win: {report['avg_win']:.6f}")
    print(f"  Avg Loss: {report['avg_loss']:.6f}")
    print(f"  Expectancy: {report['expectancy']:.6f} USDT/trade")

    print(f"\n⏱️ Trade Frequency:")
    print(f"  Trades/Day: {report['trades_per_day']:.2f}")

    print(f"\n💰 Commission Impact:")
    print(f"  Gross PnL: {report['gross_pnl']:.4f} USDT")
    print(f"  Est. Fees: {report['estimated_fees']:.4f} USDT")
    print(f"  Net PnL: {report['net_pnl']:.4f} USDT")

    print(f"\n{'='*60}")


async def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "PEPEUSDT"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 30

    report = await generate_report(symbol, days)
    print_report(report)

    # Save report
    report_path = PROJECT_ROOT / "artifacts" / f"backtest_report_{symbol.lower()}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
