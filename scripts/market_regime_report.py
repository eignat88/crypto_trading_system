#!/usr/bin/env python3
"""Market Regime Report — анализ рыночных режимов за 212 дней.

Отчёт показывает:
- Какие режимы определяет MarketRegimeDetector
- Сколько дней каждый режим
- PnL по каждому режиму
"""

from __future__ import annotations

import sys
sys.path.insert(0, '.')

from decimal import Decimal
from collections import defaultdict
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
    # Need 200 for EMA200 + 10 for slope = 210 minimum
    closes = [Decimal(str(c['close'])) for c in candles[max(0, index-250):index+1]]
    highs = [Decimal(str(c['high'])) for c in candles[max(0, index-250):index+1]]
    lows = [Decimal(str(c['low'])) for c in candles[max(0, index-250):index+1]]
    
    if len(closes) < 50:
        return MarketRegime.UNKNOWN
    
    result = detector.detect(closes, highs, lows)
    return result.regime


def analyze_regimes(symbol: str) -> dict:
    """Analyze market regimes for a symbol."""
    candles = load_candles(symbol)
    days = (candles[-1]['open_time'] - candles[0]['open_time']).days
    
    # Track regime distribution
    regime_counts = defaultdict(int)
    regime_hours = defaultdict(int)
    
    for i in range(200, len(candles)):
        regime = detect_regime(candles, i)
        regime_counts[regime.value] += 1
        regime_hours[regime.value] += 1  # Each candle = 1 hour
    
    total_candles = len(candles) - 200
    
    # Calculate percentages
    regime_stats = {}
    for regime, count in regime_counts.items():
        regime_stats[regime] = {
            'count': count,
            'hours': count,
            'days': count / 24,
            'percentage': count / total_candles * 100,
        }
    
    return {
        'symbol': symbol,
        'total_candles': total_candles,
        'total_days': days,
        'regime_stats': regime_stats,
    }


def print_report(result: dict) -> None:
    """Print formatted report."""
    print(f"\n{'='*60}")
    print(f"MARKET REGIME REPORT: {result['symbol']}")
    print(f"{'='*60}")
    
    print(f"\nTotal candles: {result['total_candles']}")
    print(f"Total days: {result['total_days']}")
    
    print(f"\nRegime Distribution:")
    print(f"{'Regime':<20} {'Days':<10} {'Hours':<10} {'%':<10}")
    print('-'*50)
    
    for regime, stats in sorted(result['regime_stats'].items(), 
                                 key=lambda x: x[1]['percentage'], reverse=True):
        print(f"{regime:<20} {stats['days']:<10.1f} {stats['hours']:<10} {stats['percentage']:<10.1f}%")
    
    print(f"\n{'='*60}")


def main():
    """Run market regime analysis."""
    for symbol in ['BTCUSDT', 'ETHUSDT']:
        result = analyze_regimes(symbol)
        print_report(result)


if __name__ == "__main__":
    main()
