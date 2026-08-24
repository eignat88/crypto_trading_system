#!/usr/bin/env python3
"""Analyze market data characteristics to select optimal strategy.

This script analyzes candle data to determine:
1. Trend vs mean-reversion characteristics
2. Volatility regime
3. Momentum patterns
4. Optimal strategy match

Usage:
    python scripts/analyze_market_data.py
    python scripts/analyze_market_data.py --symbol BTCUSDT
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


def calculate_ema(data: list[Decimal], period: int) -> list[Decimal]:
    """Calculate EMA series."""
    if len(data) < period:
        return [Decimal("0")] * len(data)
    
    k = Decimal("2") / (Decimal(str(period)) + Decimal("1"))
    ema = [sum(data[:period]) / Decimal(str(period))]
    
    for i in range(1, len(data)):
        ema.append(data[i] * k + ema[-1] * (Decimal("1") - k))
    
    return ema


def calculate_rsi(closes: list[Decimal], period: int = 14) -> Decimal:
    """Calculate RSI."""
    if len(closes) < period + 1:
        return Decimal("50")
    
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(diff))
    
    avg_gain = sum(gains[-period:]) / Decimal(str(period))
    avg_loss = sum(losses[-period:]) / Decimal(str(period))
    
    if avg_loss == 0:
        return Decimal("100")
    
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def calculate_volatility(closes: list[Decimal], period: int = 20) -> Decimal:
    """Calculate historical volatility."""
    if len(closes) < period + 1:
        return Decimal("0")
    
    returns = []
    for i in range(1, len(closes)):
        if closes[i-1] > 0:
            returns.append((closes[i] - closes[i-1]) / closes[i-1])
    
    if not returns:
        return Decimal("0")
    
    recent = returns[-period:]
    mean = sum(recent) / Decimal(str(len(recent)))
    variance = sum((r - mean) ** 2 for r in recent) / Decimal(str(len(recent)))
    
    return variance ** Decimal("0.5")


def analyze_trend(closes: list[Decimal]) -> dict:
    """Analyze trend characteristics."""
    if len(closes) < 200:
        return {"trend": "INSUFFICIENT_DATA"}
    
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    ema200 = calculate_ema(closes, 200)
    
    current = closes[-1]
    current_ema20 = ema20[-1]
    current_ema50 = ema50[-1]
    current_ema200 = ema200[-1]
    
    # Trend classification
    if current > current_ema200 and current_ema50 > current_ema200:
        trend = "STRONG_UPTREND"
        trend_score = 2
    elif current > current_ema200:
        trend = "UPTREND"
        trend_score = 1
    elif current < current_ema200 and current_ema50 < current_ema200:
        trend = "STRONG_DOWNTREND"
        trend_score = -2
    elif current < current_ema200:
        trend = "DOWNTREND"
        trend_score = -1
    else:
        trend = "RANGE"
        trend_score = 0
    
    # Trend strength (distance from EMA200)
    trend_strength = abs(current - current_ema200) / current_ema200
    
    # Trend consistency (how often EMA50 > EMA200 in last 50 candles)
    ema50_above_ema200 = sum(1 for i in range(-50, 0) if ema50[i] > ema200[i])
    trend_consistency = ema50_above_ema200 / 50
    
    return {
        "trend": trend,
        "trend_score": trend_score,
        "trend_strength": float(trend_strength),
        "trend_consistency": float(trend_consistency),
        "ema20_distance": float((current - current_ema20) / current_ema20),
        "ema50_distance": float((current - current_ema50) / current_ema50),
        "ema200_distance": float((current - current_ema200) / current_ema200),
    }


def analyze_volatility(closes: list[Decimal]) -> dict:
    """Analyze volatility characteristics."""
    if len(closes) < 50:
        return {"volatility": "INSUFFICIENT_DATA"}
    
    # Calculate ATR-like volatility
    returns = []
    for i in range(1, len(closes)):
        if closes[i-1] > 0:
            returns.append(abs((closes[i] - closes[i-1]) / closes[i-1]))
    
    # Recent volatility (last 20 periods)
    recent_vol = sum(returns[-20:]) / Decimal("20")
    
    # Historical volatility (last 100 periods)
    hist_vol = sum(returns[-100:]) / Decimal("100") if len(returns) >= 100 else recent_vol
    
    # Volatility regime
    if recent_vol > hist_vol * Decimal("1.5"):
        regime = "HIGH_VOLATILITY"
    elif recent_vol < hist_vol * Decimal("0.5"):
        regime = "LOW_VOLATILITY"
    else:
        regime = "NORMAL_VOLATILITY"
    
    return {
        "volatility": regime,
        "recent_volatility": float(recent_vol),
        "historical_volatility": float(hist_vol),
        "volatility_ratio": float(recent_vol / hist_vol) if hist_vol > 0 else 1.0,
    }


def analyze_momentum(closes: list[Decimal]) -> dict:
    """Analyze momentum characteristics."""
    if len(closes) < 20:
        return {"momentum": "INSUFFICIENT_DATA"}
    
    # RSI
    rsi = calculate_rsi(closes, 14)
    
    # Rate of change (ROC)
    roc_5 = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else Decimal("0")
    roc_10 = (closes[-1] - closes[-10]) / closes[-10] if len(closes) >= 10 else Decimal("0")
    roc_20 = (closes[-1] - closes[-20]) / closes[-20] if len(closes) >= 20 else Decimal("0")
    
    # Momentum classification
    if rsi > Decimal("70"):
        momentum = "OVERBOUGHT"
    elif rsi < Decimal("30"):
        momentum = "OVERSOLD"
    elif Decimal("45") <= rsi <= Decimal("55"):
        momentum = "NEUTRAL"
    elif rsi > Decimal("55"):
        momentum = "BULLISH"
    else:
        momentum = "BEARISH"
    
    return {
        "momentum": momentum,
        "rsi": float(rsi),
        "roc_5": float(roc_5),
        "roc_10": float(roc_10),
        "roc_20": float(roc_20),
    }


def analyze_mean_reversion(closes: list[Decimal]) -> dict:
    """Analyze mean-reversion characteristics."""
    if len(closes) < 50:
        return {"mean_reversion": "INSUFFICIENT_DATA"}
    
    # Calculate z-score relative to 20-period mean
    mean_20 = sum(closes[-20:]) / Decimal("20")
    std_20 = (sum((c - mean_20) ** 2 for c in closes[-20:]) / Decimal("20")) ** Decimal("0.5")
    
    if std_20 > 0:
        z_score = (closes[-1] - mean_20) / std_20
    else:
        z_score = Decimal("0")
    
    # Distance from mean
    distance_from_mean = abs(closes[-1] - mean_20) / mean_20
    
    # Mean reversion potential
    if abs(z_score) > Decimal("2"):
        potential = "HIGH"
    elif abs(z_score) > Decimal("1"):
        potential = "MEDIUM"
    else:
        potential = "LOW"
    
    return {
        "mean_reversion": potential,
        "z_score": float(z_score),
        "distance_from_mean": float(distance_from_mean),
        "mean_20": float(mean_20),
    }


def recommend_strategy(analysis: dict) -> dict:
    """Recommend strategy based on analysis."""
    recommendations = []
    
    trend = analysis.get("trend", {})
    volatility = analysis.get("volatility", {})
    momentum = analysis.get("momentum", {})
    mean_rev = analysis.get("mean_reversion", {})
    
    # Strategy recommendations
    trend_type = trend.get("trend", "UNKNOWN")
    vol_regime = volatility.get("volatility", "UNKNOWN")
    momentum_type = momentum.get("momentum", "UNKNOWN")
    mr_potential = mean_rev.get("mean_reversion", "UNKNOWN")
    
    # 1. Trend Following strategies
    if trend_type in ("STRONG_UPTREND", "UPTREND") and vol_regime in ("NORMAL_VOLATILITY", "LOW_VOLATILITY"):
        recommendations.append({
            "strategy": "TrendPullbackDCA",
            "reason": f"Uptrend ({trend_type}) with {vol_regime}",
            "confidence": "HIGH",
            "conditions": "Buy on pullbacks to EMA50",
        })
    
    if trend_type in ("STRONG_UPTREND", "UPTREND"):
        recommendations.append({
            "strategy": "TrendDCA",
            "reason": f"Strong trend ({trend_type})",
            "confidence": "MEDIUM",
            "conditions": "DCA on dips",
        })
    
    # 2. Mean Reversion strategies
    if mr_potential in ("HIGH", "MEDIUM") and vol_regime != "HIGH_VOLATILITY":
        recommendations.append({
            "strategy": "MeanReversion",
            "reason": f"Mean reversion potential: {mr_potential}",
            "confidence": "MEDIUM",
            "conditions": "Buy oversold, sell overbought",
        })
    
    # 3. Breakout strategies
    if vol_regime == "HIGH_VOLATILITY" or trend_type == "RANGE":
        recommendations.append({
            "strategy": "BreakoutRetest",
            "reason": f"Volatility: {vol_regime}, Trend: {trend_type}",
            "confidence": "MEDIUM",
            "conditions": "Wait for breakout confirmation",
        })
    
    # 4. Momentum strategies
    if momentum_type in ("BULLISH", "OVERSOLD") and trend_type != "STRONG_DOWNTREND":
        recommendations.append({
            "strategy": "Momentum",
            "reason": f"Momentum: {momentum_type}",
            "confidence": "MEDIUM",
            "conditions": "Follow momentum",
        })
    
    # Sort by confidence
    confidence_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recommendations.sort(key=lambda x: confidence_order.get(x["confidence"], 3))
    
    return {
        "primary_recommendation": recommendations[0] if recommendations else None,
        "all_recommendations": recommendations,
    }


async def analyze_symbol(symbol: str, candles: list[dict]) -> dict:
    """Analyze a single symbol."""
    closes = [Decimal(str(c["close"])) for c in candles]
    
    analysis = {
        "symbol": symbol,
        "candles": len(candles),
        "period": f"{candles[0]['open_time']} → {candles[-1]['open_time']}" if candles else "N/A",
        "current_price": float(closes[-1]) if closes else 0,
    }
    
    # Run analyses
    analysis["trend"] = analyze_trend(closes)
    analysis["volatility"] = analyze_volatility(closes)
    analysis["momentum"] = analyze_momentum(closes)
    analysis["mean_reversion"] = analyze_mean_reversion(closes)
    
    # Get recommendations
    analysis["recommendations"] = recommend_strategy(analysis)
    
    return analysis


async def main() -> None:
    """Main analysis function."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--output", default="artifacts/market_analysis.json")
    args = parser.parse_args()
    
    # Load candles from database
    import asyncpg
    from app.config.settings import Settings
    
    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url_sync, min_size=1, max_size=2)
    
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.open_time, c.close_price
            FROM dds.candle c
            JOIN dds.instrument i USING (instrument_id)
            WHERE i.symbol = $1 AND c.interval_code = '1h' AND c.is_valid = true
            ORDER BY c.open_time
        """, args.symbol)
        
        candles = [
            {"open_time": str(row["open_time"]), "close": float(row["close_price"])}
            for row in rows
        ]
    
    await pool.close()
    
    if not candles:
        print(f"No data found for {args.symbol}")
        return
    
    # Analyze
    analysis = await analyze_symbol(args.symbol, candles)
    
    # Print results
    print("=" * 60)
    print(f"MARKET ANALYSIS: {args.symbol}")
    print("=" * 60)
    print(f"\nCandles: {analysis['candles']}")
    print(f"Period: {analysis['period']}")
    print(f"Current price: {analysis['current_price']}")
    
    print(f"\n📊 TREND:")
    trend = analysis["trend"]
    print(f"  Type: {trend['trend']}")
    print(f"  Strength: {trend['trend_strength']:.2%}")
    print(f"  Consistency: {trend['trend_consistency']:.0%}")
    
    print(f"\n📈 VOLATILITY:")
    vol = analysis["volatility"]
    print(f"  Regime: {vol['volatility']}")
    print(f"  Recent: {vol['recent_volatility']:.2%}")
    print(f"  Historical: {vol['historical_volatility']:.2%}")
    
    print(f"\n⚡ MOMENTUM:")
    mom = analysis["momentum"]
    print(f"  RSI: {mom['rsi']:.1f}")
    print(f"  Momentum: {mom['momentum']}")
    print(f"  ROC 5: {mom['roc_5']:.2%}")
    print(f"  ROC 20: {mom['roc_20']:.2%}")
    
    print(f"\n🔄 MEAN REVERSION:")
    mr = analysis["mean_reversion"]
    print(f"  Potential: {mr['mean_reversion']}")
    print(f"  Z-score: {mr['z_score']:.2f}")
    
    print(f"\n🎯 RECOMMENDATION:")
    rec = analysis["recommendations"]
    if rec["primary_recommendation"]:
        primary = rec["primary_recommendation"]
        print(f"  Strategy: {primary['strategy']}")
        print(f"  Reason: {primary['reason']}")
        print(f"  Confidence: {primary['confidence']}")
        print(f"  Conditions: {primary['conditions']}")
    
    if len(rec["all_recommendations"]) > 1:
        print(f"\n  Alternatives:")
        for alt in rec["all_recommendations"][1:]:
            print(f"    - {alt['strategy']}: {alt['reason']} ({alt['confidence']})")
    
    # Save report
    output_path = PROJECT_ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"\nReport saved: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
