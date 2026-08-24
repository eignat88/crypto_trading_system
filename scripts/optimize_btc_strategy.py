#!/usr/bin/env python3
"""Optimize BTC Trend Pullback DCA strategy parameters.

Tests different combinations of:
- DCA levels (3, 4, 5 levels)
- Capital per level (3%, 5%, 7%, 10%)
- RSI thresholds (50, 55, 60, 65)
- ATR thresholds (0.5%, 0.7%, 1.0%, 1.5%)
- Take profit levels (5%, 8%, 10%, 15%)
- Stop loss levels (10%, 15%, 20%)

Usage:
    python scripts/optimize_btc_strategy.py
    python scripts/optimize_btc_strategy.py --balance 1000 --candles 5000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def load_candles(symbol: str, limit: int = 5000) -> list[dict]:
    """Load candles from database."""
    import asyncpg
    from app.config.settings import Settings

    settings = Settings()
    pool = await asyncpg.create_pool(settings.database_url_sync, min_size=1, max_size=2)

    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT c.open_time, c.open_price, c.high_price, c.low_price, c.close_price, c.volume
            FROM dds.candle c
            JOIN dds.instrument i USING (instrument_id)
            WHERE i.symbol = $1 AND c.interval_code = '1h' AND c.is_valid = true
            ORDER BY c.open_time DESC
            LIMIT $2
        """, symbol, limit)

    await pool.close()

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
        for row in reversed(rows)
    ]
    return candles


def calculate_indicators(candles: list[dict], index: int) -> dict:
    """Calculate indicators for a given index."""
    from app.indicators.market_regime import MarketRegime

    window = candles[max(0, index - 200):index + 1]
    if len(window) < 200:
        return {}
    closes = [Decimal(str(c["close"])) for c in window]

    # EMA
    ema20 = sum(closes[-20:]) / Decimal("20")
    ema50 = sum(closes[-50:]) / Decimal("50")
    ema200 = sum(closes[-200:]) / Decimal("200")

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
    if ema50 > ema200 and closes[-1] > ema200:
        regime = MarketRegime.TREND_UP
    elif ema50 < ema200 and closes[-1] < ema200:
        regime = MarketRegime.TREND_DOWN
    else:
        regime = MarketRegime.RANGE

    return {
        "ema_20": ema20,
        "ema_50": ema50,
        "ema_200": ema200,
        "rsi": rsi,
        "atr": atr,
        "volatility": atr / closes[-1] if closes[-1] > 0 else Decimal("0"),
        "regime": regime,
    }


def run_backtest(
    candles: list[dict],
    balance: Decimal,
    config: dict[str, Any],
) -> dict:
    """Run a single backtest with given parameters."""
    from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
    from app.strategies.btc_trend_pullback_dca import BTCTrendPullbackDCAConfig, BTCTrendPullbackDCAStrategy

    # Create config from parameters
    dca_levels = []
    for i in range(config["num_levels"]):
        dca_levels.append({
            "level": i + 1,
            "price_pct": Decimal(str(-0.03 * (i + 1))),
            "capital_pct": Decimal(str(config["capital_per_level"])) / Decimal("100"),
            "rsi_max": Decimal(str(config["rsi_max"])),
            "atr_max": Decimal(str(config["atr_max"])) / Decimal("100"),
        })

    tp_levels = []
    for i, tp_pct in enumerate(config["tp_pcts"]):
        tp_levels.append({
            "level": i + 1,
            "price_pct": Decimal(str(tp_pct)) / Decimal("100"),
            "sell_pct": Decimal(str(config["tp_sell_pcts"][i])) / Decimal("100"),
        })

    bt_config = BTCTrendPullbackDCAConfig(
        dca_levels=dca_levels,
        tp_levels=tp_levels,
        soft_sl_pct=Decimal(str(-config["sl_pct"])) / Decimal("100"),
        hard_sl_pct=Decimal(str(-config["sl_pct"] * 1.3)) / Decimal("100"),
        trailing_activation_pct=Decimal(str(config["trailing_activation"])) / Decimal("100"),
        trailing_distance_pct=Decimal(str(config["trailing_distance"])) / Decimal("100"),
    )

    strategy = BTCTrendPullbackDCAStrategy(["BTCUSDT"], config=bt_config)
    engine = BacktestEngine(config=BacktestConfig(initial_balance=balance))

    def indicator_provider(candle: dict, index: int) -> dict:
        return calculate_indicators(candles, index)

    result = engine.run(candles, strategy, indicator_provider=indicator_provider)

    return {
        "total_trades": result.total_trades,
        "win_rate": float(result.win_rate),
        "total_pnl": float(result.total_pnl),
        "pnl_pct": float(result.total_pnl / balance * 100),
        "max_drawdown": float(result.max_drawdown),
        "profit_factor": float(result.profit_factor),
        "signals": len(result.signals),
    }


async def optimize(balance: Decimal, candles_limit: int) -> None:
    """Run optimization with different parameter combinations."""
    print("=" * 70)
    print("BTC TREND PULLBACK DCA v1 — PARAMETER OPTIMIZATION")
    print("=" * 70)
    print(f"Balance: {balance} USDT")
    print(f"Candles: {candles_limit}")
    print()

    # Load candles
    print("Loading candles...")
    candles = await load_candles("BTCUSDT", candles_limit)
    print(f"Loaded {len(candles)} candles")
    print()

    # Parameter grid
    param_grid = {
        "num_levels": [3, 4, 5],
        "capital_per_level": [3, 5, 7, 10],
        "rsi_max": [50, 55, 60, 65],
        "atr_max": [50, 70, 100, 150],  # basis points (0.5% = 50)
        "tp_pcts": [[5, 10, 15], [8, 12, 18], [10, 15, 20]],
        "tp_sell_pcts": [[30, 30, 40], [25, 35, 40], [20, 30, 50]],
        "sl_pct": [10, 15, 20],
        "trailing_activation": [5, 8, 10],
        "trailing_distance": [3, 4, 5],
    }

    # Run optimization
    results = []
    total_combos = 1
    for key, values in param_grid.items():
        if isinstance(values[0], list):
            total_combos *= len(values)
        else:
            total_combos *= len(values)

    print(f"Testing {total_combos} parameter combinations...")
    print()

    combo_num = 0
    for num_levels in param_grid["num_levels"]:
        for capital in param_grid["capital_per_level"]:
            for rsi in param_grid["rsi_max"]:
                for atr in param_grid["atr_max"]:
                    for tp_pcts in param_grid["tp_pcts"]:
                        for tp_sell in param_grid["tp_sell_pcts"]:
                            for sl in param_grid["sl_pct"]:
                                for trail_act in param_grid["trailing_activation"]:
                                    for trail_dist in param_grid["trailing_distance"]:
                                        combo_num += 1

                                        config = {
                                            "num_levels": num_levels,
                                            "capital_per_level": capital,
                                            "rsi_max": rsi,
                                            "atr_max": atr,
                                            "tp_pcts": tp_pcts,
                                            "tp_sell_pcts": tp_sell,
                                            "sl_pct": sl,
                                            "trailing_activation": trail_act,
                                            "trailing_distance": trail_dist,
                                        }

                                        try:
                                            result = run_backtest(candles, balance, config)
                                            result["config"] = config
                                            results.append(result)
                                        except Exception as e:
                                            pass

                                        if combo_num % 100 == 0:
                                            print(f"  Progress: {combo_num}/{total_combos}")

    # Sort by PnL
    results.sort(key=lambda x: x["total_pnl"], reverse=True)

    # Print top 10
    print("\n" + "=" * 70)
    print("TOP 10 PARAMETER COMBINATIONS")
    print("=" * 70)

    for i, result in enumerate(results[:10]):
        config = result["config"]
        print(f"\n#{i+1}:")
        print(f"  PnL: {result['total_pnl']:.2f} USDT ({result['pnl_pct']:.2f}%)")
        print(f"  Win rate: {result['win_rate']:.1%}")
        print(f"  Max drawdown: {result['max_drawdown']:.2%}")
        print(f"  Trades: {result['total_trades']}")
        print(f"  Config: levels={config['num_levels']}, capital={config['capital_per_level']}%, rsi<{config['rsi_max']}, atr<{config['atr_max']/100:.1f}%")
        print(f"  TP: {config['tp_pcts']}%, SL: {config['sl_pct']}%")
        print(f"  Trailing: +{config['trailing_activation']}%/{config['trailing_distance']}%")

    # Save results
    output_path = PROJECT_ROOT / "artifacts" / "optimization_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results[:50], f, indent=2, default=str)  # Save top 50

    print(f"\nResults saved: {output_path}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--balance", type=Decimal, default=Decimal("1000"))
    parser.add_argument("--candles", type=int, default=5000)
    args = parser.parse_args()

    asyncio.run(optimize(args.balance, args.candles))


if __name__ == "__main__":
    main()
