"""Strategy Selector — выбор стратегии на основе Market Regime.

Архитектура:
Market Regime Engine → Strategy Selector → Strategy

Режимы рынка и разрешённые стратегии:
- TREND_UP → TrendDCA
- TREND_DOWN → NO TRADE (Spot)
- SIDEWAYS → MeanReversion (если есть)
- HIGH_VOLATILITY → Уменьшить размер позиции
"""

from __future__ import annotations

from typing import Any

import structlog

from app.indicators.market_regime import MarketRegime
from app.strategies.base_strategy import BaseStrategy

logger = structlog.get_logger()


class StrategySelector:
    """Choose the right strategy based on market regime.

    Architecture:
    Market Regime Engine
           |
           v
    Strategy Selector
           |
    +------+------+
    |             |
    v             v
    TrendDCA   MeanReversion
    """

    def __init__(
        self,
        strategies: dict[str, BaseStrategy],
        default_strategy: str | None = None,
    ) -> None:
        """
        Args:
            strategies: Dict mapping regime names to strategy instances
            default_strategy: Fallback strategy if regime is unknown
        """
        self.strategies = strategies
        self.default_strategy = default_strategy
        self._current_regime: MarketRegime | None = None
        self._current_strategy: BaseStrategy | None = None

    def select(self, regime: MarketRegime) -> BaseStrategy | None:
        """Select strategy based on market regime.

        Args:
            regime: Current market regime

        Returns:
            Strategy instance or None if no trade allowed
        """
        self._current_regime = regime

        # Map regime to strategy
        regime_map = {
            MarketRegime.TREND_UP: "trend_dca",
            MarketRegime.TREND_DOWN: None,  # No trade in downtrend (Spot)
            MarketRegime.RANGE: "mean_reversion",
            MarketRegime.HIGH_VOLATILITY: None,  # Reduce position size
            MarketRegime.UNKNOWN: self.default_strategy,
        }

        strategy_name = regime_map.get(regime)

        if strategy_name is None:
            logger.info("strategy_selector_no_trade", regime=regime.value)
            self._current_strategy = None
            return None

        strategy = self.strategies.get(strategy_name)
        if strategy is None:
            logger.warning("strategy_selector_not_found", strategy=strategy_name)
            self._current_strategy = None
            return None

        logger.info(
            "strategy_selected",
            regime=regime.value,
            strategy=strategy.name,
        )
        self._current_strategy = strategy
        return strategy

    def get_position_multiplier(self, regime: MarketRegime) -> Decimal:
        """Get position size multiplier based on regime.

        Returns:
            Multiplier for position sizing (e.g., 0.5 for half size)
        """
        multipliers = {
            MarketRegime.TREND_UP: Decimal("1.0"),      # Full size
            MarketRegime.TREND_DOWN: Decimal("0.0"),    # No trading
            MarketRegime.RANGE: Decimal("0.5"),          # Half size
            MarketRegime.HIGH_VOLATILITY: Decimal("0.3"),  # 30% size
            MarketRegime.UNKNOWN: Decimal("0.5"),        # Half size
        }
        return multipliers.get(regime, Decimal("0.5"))

    @property
    def current_regime(self) -> MarketRegime | None:
        return self._current_regime

    @property
    def current_strategy(self) -> BaseStrategy | None:
        return self._current_strategy

    def get_status(self) -> dict:
        """Get current selector status."""
        return {
            "regime": self._current_regime.value if self._current_regime else None,
            "strategy": self._current_strategy.name if self._current_strategy else None,
            "position_multiplier": float(self.get_position_multiplier(self._current_regime)) if self._current_regime else 0,
            "available_strategies": list(self.strategies.keys()),
        }
