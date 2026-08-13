"""CTS MVP v2.3.1 strategy wrapper for BacktestEngine.

This class bridges the existing BaseStrategy contract with the CTS
BacktestAdapter. Indicator calculation remains outside the strategy.
"""

from __future__ import annotations

from typing import Any

from app.models import Signal
from app.strategies.base_strategy import BaseStrategy
from app.strategies.cts_backtest_adapter import CTSBacktestAdapter


class CTSBacktestStrategy(BaseStrategy):
    """Expose CTS signals through the existing BacktestEngine strategy API."""

    def __init__(self, symbols: list[str]) -> None:
        super().__init__(name="CTS_MVP_v2.3.1", symbols=symbols)
        self.adapter = CTSBacktestAdapter()

    def should_enter(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        portfolio_state: dict[str, Any],
    ) -> Signal | None:
        return self.adapter.generate_signal(
            candle=candle,
            indicators=indicators,
            state=self.state,
        )

    def should_exit(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        position: dict[str, Any],
    ) -> Signal | None:
        return None

    def on_bar(
        self,
        candle: dict[str, Any],
        indicators: dict[str, Any],
    ) -> None:
        self.state.update(indicators.get("cts_state", {}))
