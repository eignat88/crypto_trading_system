#!/usr/bin/env python3
"""Backtest with Market Regime Engine — тестирование стратегий в разных режимах.

Архитектура:
Market Regime Engine → Strategy Selector → Strategy

Режимы рынка:
- TREND_UP → TrendDCA
- SIDEWAYS → MeanReversion
- HIGH_VOLATILITY → Уменьшить размер позиции
- TREND_DOWN → NO TRADE
"""

from __future__ import annotations

import sys
sys.path.insert(0, '.')

from decimal import Decimal
from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.strategies.trend_follow_simple import TrendFollowSimpleStrategy
from app.indicators.market_regime import MarketRegime, MarketRegimeDetector
from app.indicators.rsi import calculate_rsi
import psycopg
from app.config.settings import settings


def load_candles(symbol: str) -> list[dict]:
    """Load candles from database."""
    conn = psycopg.connect(
        host=settings.postgres_host, port=settings.postgres_port,
        dbname=settings.postgres_db, user=settings.postgres_user,
        password=settings.postgres_password,
    )
    with conn.cursor() as cur:
        cur.execute('''
            SELECT c.open_time, c.open_price, c.high_price, c.low_price, c.close_price, c.volume
            FROM dds.candle c JOIN dds.instrument i USING (instrument_id)
            WHERE i.symbol = %s AND c.interval_code = '1h' AND c.is_valid = true
            ORDER BY c.open_time
        ''', (symbol,))
        rows = cur.fetchall()
    conn.close()
    return [{'symbol': symbol, 'open_time': r[0], 'open': Decimal(str(r[1])),
             'high': Decimal(str(r[2])), 'low': Decimal(str(r[3])),
             'close': Decimal(str(r[4])), 'volume': Decimal(str(r[5]))} for r in rows]


def detect_regime(candles: list[dict], index: int) -> MarketRegime:
    """Detect market regime for given candle index."""
    detector = MarketRegimeDetector()
    
    # Get price data
    closes = [Decimal(str(c['close'])) for c in candles[max(0, index-200):index+1]]
    highs = [Decimal(str(c['high'])) for c in candles[max(0, index-200):index+1]]
    lows = [Decimal(str(c['low'])) for c in candles[max(0, index-200):index+1]]
    
    if len(closes) < 50:
        return MarketRegime.UNKNOWN
    
    result = detector.detect(closes, highs, lows)
    return result.regime


def calculate_indicators(candles: list[dict], index: int) -> dict:
    """Calculate indicators for given candle index."""
    w = candles[max(0, index - 200):index + 1]
    if len(w) < 50:
        return {}
    closes = [Decimal(str(x['close'])) for x in w]
    ema20 = sum(closes[-20:]) / Decimal('20')
    ema50 = sum(closes[-50:]) / Decimal('50')
    ema200 = sum(closes[-200:]) / Decimal('200') if len(closes) >= 200 else ema50
    rsi = calculate_rsi(closes, 14) or Decimal('50')
    h = [Decimal(str(x['high'])) for x in w[-14:]]
    lo = [Decimal(str(x['low'])) for x in w[-14:]]
    atr = sum(x - y for x, y in zip(h, lo)) / Decimal('14')
    return {'ema_20': ema20, 'ema_50': ema50, 'ema_200': ema200, 'rsi': rsi, 'atr': atr,
            'regime': MarketRegime.TREND_UP if ema50 > ema200 else MarketRegime.RANGE}


def run_regime_backtest(symbol: str) -> dict:
    """Run backtest with regime-based strategy selection."""
    candles = load_candles(symbol)
    days = (candles[-1]['open_time'] - candles[0]['open_time']).days
    
    balance = Decimal('1000')
    
    # Track regime statistics
    regime_stats = {
        MarketRegime.TREND_UP: {"trades": 0, "wins": 0, "pnl": Decimal("0")},
        MarketRegime.TREND_DOWN: {"trades": 0, "wins": 0, "pnl": Decimal("0")},
        MarketRegime.RANGE: {"trades": 0, "wins": 0, "pnl": Decimal("0")},
        MarketRegime.HIGH_VOLATILITY: {"trades": 0, "wins": 0, "pnl": Decimal("0")},
    }
    
    # Create strategy
    strategy = TrendFollowSimpleStrategy([symbol])
    
    # Run backtest
    engine = BacktestEngine(config=BacktestConfig(initial_balance=balance))
    
    def indicator_provider(candle: dict, index: int) -> dict:
        indicators = calculate_indicators(candles, index)
        regime = detect_regime(candles, index)
        indicators['regime'] = regime
        return indicators
    
    result = engine.run(candles, strategy, indicator_provider=indicator_provider)
    
    # Analyze results by regime
    for signal in result.signals:
        regime = signal.metadata.get('regime', MarketRegime.UNKNOWN)
        if regime in regime_stats:
            regime_stats[regime]["trades"] += 1
    
    return {
        'symbol': symbol,
        'days': days,
        'total_trades': result.total_trades,
        'win_rate': float(result.win_rate),
        'pnl': float(result.total_pnl),
        'pnl_pct': float(result.total_pnl / balance * 100),
        'max_dd': float(result.max_drawdown),
        'pf': float(result.profit_factor),
        'regime_stats': {k.value: v for k, v in regime_stats.items()},
    }


def main():
    """Run regime-based backtest."""
    print('='*80)
    print('REGIME-BASED BACKTEST (212 days, 10% position)')
    print('='*80)
    
    for symbol in ['BTCUSDT', 'ETHUSDT']:
        result = run_regime_backtest(symbol)
        print(f'\n{result["symbol"]}:')
        print(f'  Total trades: {result["total_trades"]}')
        print(f'  Win rate: {result["win_rate"]:.1%}')
        print(f'  PnL: {result["pnl_pct"]:.3f}%')
        print(f'  Max DD: {result["max_dd"]:.2%}')
        print(f'  PF: {result["pf"]:.2f}')
        
        print(f'\n  Regime breakdown:')
        for regime, stats in result['regime_stats'].items():
            if stats['trades'] > 0:
                print(f'    {regime}: {stats["trades"]} trades')


if __name__ == "__main__":
    main()
