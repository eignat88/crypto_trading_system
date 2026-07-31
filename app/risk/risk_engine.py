"""Fail-closed pre-trade risk controls and durable risk-state hooks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol

import structlog

logger = structlog.get_logger()


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskEvent(StrEnum):
    MAX_RISK_PER_TRADE = "MAX_RISK_PER_TRADE"
    MAX_POSITION_SIZE = "MAX_POSITION_SIZE"
    MAX_ASSET_EXPOSURE = "MAX_ASSET_EXPOSURE"
    MAX_CAPITAL_UTILIZATION = "MAX_CAPITAL_UTILIZATION"
    INSUFFICIENT_BALANCE = "INSUFFICIENT_BALANCE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    STALE_DATA = "STALE_DATA"
    API_UNAVAILABLE = "API_UNAVAILABLE"
    DATABASE_UNAVAILABLE = "DATABASE_UNAVAILABLE"
    RECONCILIATION_FAILED = "RECONCILIATION_FAILED"
    UNKNOWN_ORDER_STATUS = "UNKNOWN_ORDER_STATUS"
    INVALID_TRADE = "INVALID_TRADE"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"


@dataclass
class RiskConfig:
    max_risk_per_trade: Decimal = Decimal("0.005")
    max_position_size: Decimal = Decimal("0.10")
    max_asset_exposure: Decimal = Decimal("0.25")
    max_capital_utilization: Decimal = Decimal("0.60")
    daily_loss_limit: Decimal = Decimal("0.02")
    weekly_loss_limit: Decimal = Decimal("0.05")
    max_drawdown: Decimal = Decimal("0.10")
    max_open_positions: int = 5
    stale_data_threshold_minutes: int = 5


@dataclass
class RiskCheckResult:
    approved: bool
    risk_level: RiskLevel
    reasons: list[str]
    events: list[RiskEvent]
    adjusted_quantity: Decimal | None = None


class RiskStateStore(Protocol):
    """Synchronous persistence boundary; production implementations may use PostgreSQL."""

    def load_state(self) -> dict[str, Any] | None: ...

    def save_state(self, state: dict[str, Any]) -> None: ...

    def save_event(self, event: dict[str, Any]) -> None: ...


KNOWN_ORDER_STATUSES = frozenset(
    {"new", "created", "open", "partially_filled", "filled", "cancelled", "canceled", "rejected"}
)


class RiskEngine:
    """Validate every trade request; missing operational certainty blocks new risk."""

    def __init__(self, config: RiskConfig | None = None, state_store: RiskStateStore | None = None):
        self.config = config or RiskConfig()
        self.state_store = state_store
        self.daily_pnl = Decimal("0")
        self.weekly_pnl = Decimal("0")
        self.peak_equity = Decimal("0")
        self.current_equity = Decimal("0")
        self.is_emergency_stop = False
        self.emergency_stop_reason = ""
        self.last_data_time: datetime | None = None
        self.consecutive_errors = 0
        self.database_available = True
        self.api_available = True
        self.reconciliation_ok = True
        if state_store:
            state = state_store.load_state()
            if state:
                self._restore_state(state)

    @staticmethod
    def _position_signed_value(position: dict[str, Any]) -> Decimal:
        value = Decimal(str(position.get("value", 0)))
        side = str(position.get("side", "buy")).lower()
        return -abs(value) if side in {"sell", "short"} else abs(value)

    def check_trade(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        current_balance: Decimal,
        current_positions: dict[str, dict[str, Any]],
        total_capital: Decimal,
        *,
        stop_loss_price: Decimal | None = None,
        database_available: bool | None = None,
        api_available: bool | None = None,
        reconciliation_ok: bool | None = None,
        order_statuses: list[str] | None = None,
    ) -> RiskCheckResult:
        reasons: list[str] = []
        events: list[RiskEvent] = []
        risk_level = RiskLevel.LOW

        def reject(reason: str, event: RiskEvent, level: RiskLevel = RiskLevel.HIGH) -> None:
            nonlocal risk_level
            reasons.append(reason)
            events.append(event)
            if list(RiskLevel).index(level) > list(RiskLevel).index(risk_level):
                risk_level = level

        side = side.lower()
        if side not in {"buy", "sell"} or quantity <= 0 or price <= 0 or total_capital <= 0:
            reject(
                "Trade side and monetary values must be valid",
                RiskEvent.INVALID_TRADE,
                RiskLevel.CRITICAL,
            )
        if self.is_emergency_stop:
            reject("Emergency stop is active", RiskEvent.EMERGENCY_STOP, RiskLevel.CRITICAL)
        if not (self.database_available if database_available is None else database_available):
            reject("PostgreSQL is unavailable", RiskEvent.DATABASE_UNAVAILABLE, RiskLevel.CRITICAL)
        if not (self.api_available if api_available is None else api_available):
            reject("Exchange API is unavailable", RiskEvent.API_UNAVAILABLE, RiskLevel.CRITICAL)
        if not (self.reconciliation_ok if reconciliation_ok is None else reconciliation_ok):
            reject(
                "Latest reconciliation did not succeed",
                RiskEvent.RECONCILIATION_FAILED,
                RiskLevel.CRITICAL,
            )
        unknown = sorted(
            {s for s in (order_statuses or []) if s.lower() not in KNOWN_ORDER_STATUSES}
        )
        if unknown:
            reject(
                f"Unknown order status: {', '.join(unknown)}",
                RiskEvent.UNKNOWN_ORDER_STATUS,
                RiskLevel.CRITICAL,
            )
        if self.last_data_time:
            timestamp = self.last_data_time
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - timestamp).total_seconds() / 60
            if age > self.config.stale_data_threshold_minutes:
                reject(f"Data is stale: {age:.1f} minutes old", RiskEvent.STALE_DATA)

        order_value = quantity * price
        symbol_positions = [p for p in current_positions.values() if p.get("symbol") == symbol]
        before = sum((self._position_signed_value(p) for p in symbol_positions), Decimal("0"))
        delta = order_value if side == "buy" else -order_value
        after = before + delta
        exposure_increase = max(abs(after) - abs(before), Decimal("0"))
        reducing = exposure_increase == 0

        if not reducing:
            position_pct = exposure_increase / total_capital
            if position_pct > self.config.max_position_size:
                reject(
                    f"Position size {position_pct:.2%} exceeds limit "
                    f"{self.config.max_position_size:.2%}",
                    RiskEvent.MAX_POSITION_SIZE,
                )
            if exposure_increase > current_balance:
                reject(
                    f"Available balance {current_balance} is below required {exposure_increase}",
                    RiskEvent.INSUFFICIENT_BALANCE,
                )
            if stop_loss_price is not None:
                risk_amount = (exposure_increase / price) * abs(price - stop_loss_price)
                risk_pct = risk_amount / total_capital
                if risk_pct > self.config.max_risk_per_trade:
                    reject(
                        f"Trade risk {risk_pct:.2%} exceeds limit "
                        f"{self.config.max_risk_per_trade:.2%}",
                        RiskEvent.MAX_RISK_PER_TRADE,
                    )

        asset_pct = abs(after) / total_capital
        if not reducing and asset_pct > self.config.max_asset_exposure:
            reject(
                f"Asset exposure {asset_pct:.2%} exceeds limit "
                f"{self.config.max_asset_exposure:.2%}",
                RiskEvent.MAX_ASSET_EXPOSURE,
            )
        other_exposure = sum(
            (
                abs(self._position_signed_value(p))
                for p in current_positions.values()
                if p.get("symbol") != symbol
            ),
            Decimal("0"),
        )
        utilization = (other_exposure + abs(after)) / total_capital
        if not reducing and utilization > self.config.max_capital_utilization:
            reject(
                f"Capital utilization {utilization:.2%} exceeds limit "
                f"{self.config.max_capital_utilization:.2%}",
                RiskEvent.MAX_CAPITAL_UTILIZATION,
            )
        if (
            self.daily_pnl < 0
            and abs(self.daily_pnl) / total_capital > self.config.daily_loss_limit
        ):
            reject("Daily loss limit exceeded", RiskEvent.DAILY_LOSS_LIMIT, RiskLevel.CRITICAL)
        if (
            self.weekly_pnl < 0
            and abs(self.weekly_pnl) / total_capital > self.config.weekly_loss_limit
        ):
            reject("Weekly loss limit exceeded", RiskEvent.WEEKLY_LOSS_LIMIT, RiskLevel.CRITICAL)
        if (
            self.peak_equity > 0
            and (self.peak_equity - self.current_equity) / self.peak_equity
            > self.config.max_drawdown
        ):
            reject("Maximum drawdown exceeded", RiskEvent.MAX_DRAWDOWN, RiskLevel.CRITICAL)
        if (
            not reducing
            and symbol not in {p.get("symbol") for p in current_positions.values()}
            and len(current_positions) >= self.config.max_open_positions
        ):
            reject(
                f"Too many open positions: {len(current_positions)}",
                RiskEvent.MAX_POSITION_SIZE,
                RiskLevel.MEDIUM,
            )

        adjusted_quantity = None
        if RiskEvent.MAX_POSITION_SIZE in events:
            adjusted_quantity = total_capital * self.config.max_position_size / price
            reasons.append(f"Adjusted quantity to {adjusted_quantity}")
        result = RiskCheckResult(not reasons, risk_level, reasons, events, adjusted_quantity)
        if events:
            self._persist_events(symbol, side, quantity, price, result)
            logger.warning("trade_rejected", symbol=symbol, side=side, reasons=reasons)
        return result

    def _persist_events(
        self, symbol: str, side: str, quantity: Decimal, price: Decimal, result: RiskCheckResult
    ) -> None:
        if not self.state_store:
            return
        occurred_at = datetime.now(UTC).isoformat()
        for event in result.events:
            self.state_store.save_event(
                {
                    "event_type": event.value,
                    "risk_level": result.risk_level.value,
                    "symbol": symbol,
                    "side": side,
                    "quantity": str(quantity),
                    "price": str(price),
                    "reasons": result.reasons,
                    "occurred_at": occurred_at,
                }
            )

    def _state(self) -> dict[str, Any]:
        return {
            "daily_pnl": str(self.daily_pnl),
            "weekly_pnl": str(self.weekly_pnl),
            "peak_equity": str(self.peak_equity),
            "current_equity": str(self.current_equity),
            "is_emergency_stop": self.is_emergency_stop,
            "emergency_stop_reason": self.emergency_stop_reason,
            "consecutive_errors": self.consecutive_errors,
        }

    def _restore_state(self, state: dict[str, Any]) -> None:
        for field in ("daily_pnl", "weekly_pnl", "peak_equity", "current_equity"):
            setattr(self, field, Decimal(str(state.get(field, "0"))))
        self.is_emergency_stop = bool(state.get("is_emergency_stop", False))
        self.emergency_stop_reason = str(state.get("emergency_stop_reason", ""))
        self.consecutive_errors = int(state.get("consecutive_errors", 0))

    def _save_state(self) -> None:
        if self.state_store:
            self.state_store.save_state(self._state())

    def update_system_health(self, *, database_available: bool, api_available: bool) -> None:
        self.database_available, self.api_available = database_available, api_available

    def update_reconciliation(self, successful: bool) -> None:
        self.reconciliation_ok = successful

    def update_pnl(self, daily_pnl: Decimal, weekly_pnl: Decimal) -> None:
        self.daily_pnl, self.weekly_pnl = daily_pnl, weekly_pnl
        self._save_state()

    def update_equity(self, equity: Decimal) -> None:
        self.current_equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        self._save_state()

    def set_emergency_stop(self, active: bool, reason: str = "") -> None:
        self.is_emergency_stop, self.emergency_stop_reason = active, reason if active else ""
        self._save_state()
        logger.critical("emergency_stop_activated", reason=reason) if active else logger.info(
            "emergency_stop_deactivated"
        )

    def update_data_time(self, timestamp: datetime) -> None:
        self.last_data_time = timestamp

    def record_error(self) -> None:
        self.consecutive_errors += 1
        if self.consecutive_errors >= 5:
            self.set_emergency_stop(True, "Too many consecutive errors")
        else:
            self._save_state()

    def reset_errors(self) -> None:
        self.consecutive_errors = 0
        self._save_state()

    def reset_daily(self) -> None:
        self.daily_pnl = Decimal("0")
        self._save_state()

    def reset_weekly(self) -> None:
        self.weekly_pnl = Decimal("0")
        self._save_state()
