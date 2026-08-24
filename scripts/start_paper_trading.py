#!/usr/bin/env python3
"""Start paper trading with Breakout Retest v2 strategy.

Usage:
    python scripts/start_paper_trading.py
"""

import asyncio
import sys
from datetime import datetime, UTC
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from app.config.settings import settings
from app.strategies.breakout_retest_v2 import BreakoutRetestV2Strategy
from app.exchange.paper_execution_engine import ExecutionRequest, OrderSide, PaperExecutionEngine
from app.models.candle import Candle
from app.indicators.ema import calculate_ema
from app.indicators.atr import calculate_atr
from app.indicators.volume import calculate_average_volume
from app.indicators.market_regime import MarketRegime


structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.stdlib.NAME_TO_LEVEL[settings.log_level.lower()]
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class StrategyAdapter:
    """Adapter to make BreakoutRetestV2 work with PaperTradingRuntime."""

    def __init__(self, strategy: BreakoutRetestV2Strategy):
        self.strategy = strategy
        self._indicator_cache: dict[str, dict] = {}

    def _compute_indicators(self, candle: Candle) -> dict:
        """Compute indicators from candle data."""
        symbol = candle.symbol
        if symbol not in self._indicator_cache:
            self._indicator_cache[symbol] = {"closes": [], "highs": [], "lows": [], "volumes": []}

        cache = self._indicator_cache[symbol]
        cache["closes"].append(candle.close)
        cache["highs"].append(candle.high)
        cache["lows"].append(candle.low)
        cache["volumes"].append(candle.volume)

        # Keep last 300 candles
        for key in cache:
            if len(cache[key]) > 300:
                cache[key] = cache[key][-300:]

        closes = cache["closes"]
        highs = cache["highs"]
        lows = cache["lows"]
        volumes = cache["volumes"]

        ema20 = calculate_ema(closes, 20)
        ema50 = calculate_ema(closes, 50)
        ema200 = calculate_ema(closes, 200)
        atr = calculate_atr(highs, lows, closes, 14)
        volume_ma20 = calculate_average_volume(volumes, 20)

        # Simple RSI calculation
        rsi = None
        if len(closes) >= 15:
            gains = []
            losses = []
            for i in range(-14, 0):
                diff = closes[i] - closes[i - 1]
                if diff > 0:
                    gains.append(diff)
                    losses.append(Decimal("0"))
                else:
                    gains.append(Decimal("0"))
                    losses.append(abs(diff))
            avg_gain = sum(gains) / 14
            avg_loss = sum(losses) / 14
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            else:
                rsi = Decimal("100")

        # Market regime
        regime = MarketRegime.UNKNOWN
        if ema20 and ema50 and ema200:
            if ema20 > ema50 > ema200:
                regime = MarketRegime.TREND_UP
            elif ema20 < ema50 < ema200:
                regime = MarketRegime.TREND_DOWN

        # Volatility
        volatility = None
        if atr and candle.close > 0:
            volatility = atr / candle.close

        return {
            "ema_20": ema20,
            "ema_50": ema50,
            "ema_200": ema200,
            "rsi": rsi,
            "regime": regime,
            "volatility": volatility,
            "atr": atr,
            "volume_ma20": volume_ma20,
        }

    async def on_candle(self, candle: Candle, engine: PaperExecutionEngine) -> list[ExecutionRequest]:
        """Process candle and return execution requests."""
        indicators = self._compute_indicators(candle)

        candle_dict = {
            "symbol": candle.symbol,
            "open_time": candle.open_time,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }

        portfolio_state = {
            "capital": engine.cash_balance,
            "has_position": candle.symbol in engine.positions,
        }

        requests = []

        # Check exit first
        if candle.symbol in engine.positions:
            position = engine.positions[candle.symbol]
            position_dict = {
                "entry_price": position.average_price,
                "quantity": position.quantity,
            }
            exit_signal = self.strategy.should_exit(candle_dict, indicators, position_dict)
            if exit_signal is not None:
                requests.append(ExecutionRequest(
                    symbol=exit_signal.symbol,
                    side=OrderSide.SELL,
                    quantity=exit_signal.quantity,
                ))
                return requests

        # Check entry
        entry_signal = self.strategy.should_enter(candle_dict, indicators, portfolio_state)
        if entry_signal is not None:
            requests.append(ExecutionRequest(
                symbol=entry_signal.symbol,
                side=OrderSide.BUY,
                quantity=entry_signal.quantity,
            ))

        return requests


async def main():
    """Start paper trading runtime with Breakout Retest v2."""
    logger.info("=" * 60)
    logger.info("  CRYPTO PAPER TRADING SYSTEM")
    logger.info("  Strategy: Breakout Retest v2")
    logger.info("=" * 60)
    logger.info(f"  Mode: {settings.trading_mode.value}")
    logger.info(f"  Exchange: {settings.bybit_environment}")
    logger.info(f"  Capital: ${settings.paper_initial_balance:,.0f}")

    symbols = [
        s.strip().removesuffix("-SPOT")
        for s in settings.trading_symbols.split(",")
        if s.strip()
    ]
    logger.info(f"  Symbols: {symbols}")
    logger.info("=" * 60)

    # Build dependencies
    from app.runtime.dependencies import build_paper_dependencies
    deps = await build_paper_dependencies(settings)

    # Create strategy and adapter
    strategy = BreakoutRetestV2Strategy(symbols=symbols)
    adapter = StrategyAdapter(strategy)
    deps.runtime.strategy = adapter
    logger.info(f"  Strategy wired: {strategy.name} (via adapter)")

    # Run
    app = PaperApplication(deps)
    await app.run()


from app.runtime.paper_application import PaperApplication


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
