"""Read-only operational view of the risk engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class RiskHealthStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class RiskHealthResult:
    risk_status: RiskHealthStatus
    capital_usage: Decimal
    drawdown: Decimal
    trading_enabled: bool
    reasons: tuple[str, ...] = ()


class RiskHealthMonitor:
    def check(self, engine: Any, *, capital_usage: Decimal = Decimal("0")) -> RiskHealthResult:
        reasons: list[str] = []
        peak = Decimal(str(getattr(engine, "peak_equity", 0)))
        equity = Decimal(str(getattr(engine, "current_equity", 0)))
        drawdown = (peak - equity) / peak if peak > 0 else Decimal("0")
        config = engine.config
        critical = False
        checks = (
            (bool(getattr(engine, "is_emergency_stop", False)), "emergency stop active"),
            (not bool(getattr(engine, "database_available", True)), "database unavailable"),
            (not bool(getattr(engine, "reconciliation_ok", True)), "reconciliation failed"),
            (drawdown > config.max_drawdown, "maximum drawdown exceeded"),
            (
                abs(min(Decimal(str(getattr(engine, "daily_pnl", 0))), Decimal("0")))
                > max(equity, Decimal("0")) * config.daily_loss_limit,
                "daily loss exceeded",
            ),
        )
        for failed, reason in checks:
            if failed:
                reasons.append(reason)
                critical = True
        if capital_usage > config.max_capital_utilization:
            reasons.append("capital utilization exceeded")
            critical = True
        status = RiskHealthStatus.CRITICAL if critical else RiskHealthStatus.OK
        return RiskHealthResult(status, capital_usage, drawdown, not critical, tuple(reasons))
