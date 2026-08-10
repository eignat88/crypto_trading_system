from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.models import Signal
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy


EXPERIMENT_PARAMETERS_VERSION = "trend_dca_v1_ema200_slope_train_p75"


class TrendDCAEMA200SlopeP75Strategy(TrendDCAStrategy):
    """TrendDCA with one additional base-entry filter.

    The threshold is derived outside the strategy from the current walk-forward
    TRAIN slice and is frozen for the corresponding TEST slice. Exit logic,
    DCA logic, position sizing, RSI, TP/SL and trailing behavior are inherited
    unchanged from the baseline TrendDCA strategy.
    """

    def __init__(self, symbols: list[str], ema200_slope_threshold: Decimal) -> None:
        super().__init__(
            symbols=symbols,
            config=DCAConfig(parameters_version=EXPERIMENT_PARAMETERS_VERSION),
        )
        self.ema200_slope_threshold = ema200_slope_threshold

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        slope = indicators.get("ema200_slope_10")
        if slope is None:
            return None
        slope_value = Decimal(str(slope))
        if slope_value < self.ema200_slope_threshold:
            return None

        signal = super().should_enter(candle, indicators, portfolio_state)
        if signal is None:
            return None

        signal.metadata = {
            **signal.metadata,
            "ema200_slope_10": str(slope_value),
            "ema200_slope_threshold": str(self.ema200_slope_threshold),
            "threshold_source": "TRAIN_ENTRY_OPPORTUNITY_P75",
        }
        return signal
