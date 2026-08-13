"""Adapter between CTS MVP v2.3.1 signals and backtest execution.

This module intentionally does not calculate indicators and does not execute
orders. It converts a confirmed CTS state into the existing Signal domain model.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from app.models import Signal, SignalAction


class CTSBacktestAdapter:
    """Create backtest signals from already calculated CTS state."""

    STRATEGY_VERSION = "CTS_MVP_v2.3.1"

    def generate_signal(
        self,
        *,
        candle: dict[str, Any],
        indicators: dict[str, Any],
        state: dict[str, Any],
    ) -> Signal | None:
        """Return BUY signal only for confirmed CTS DCA entry state."""

        if state.get("pullback_state") != "LOCKED":
            return None

        if not state.get("cooldown_ready", False):
            return None

        if not state.get("dca_signal", False):
            return None

        return Signal(
            action=SignalAction.BUY,
            symbol=str(candle["symbol"]),
            price=Decimal(str(candle["close"])),
            quantity=Decimal("0"),
            timestamp=candle.get("timestamp", datetime.now(UTC)),
            reason="CTS_TREND_DCA_CONFIRMATION",
            strategy=self.STRATEGY_VERSION,
            parameters_version=self.STRATEGY_VERSION,
            indicators=indicators,
            regime=str(state.get("regime", "UNKNOWN")),
            metadata={"source": "cts_backtest_adapter"},
        )
