from decimal import Decimal
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import structlog

logger = structlog.get_logger()


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskEvent(str, Enum):
    MAX_POSITION_SIZE = "MAX_POSITION_SIZE"
    MAX_ASSET_EXPOSURE = "MAX_ASSET_EXPOSURE"
    MAX_CAPITAL_UTILIZATION = "MAX_CAPITAL_UTILIZATION"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    WEEKLY_LOSS_LIMIT = "WEEKLY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    EMERGENCY_STOP = "EMERGENCY_STOP"
    STALE_DATA = "STALE_DATA"
    API_UNAVAILABLE = "API_UNAVAILABLE"
    BALANCE_MISMATCH = "BALANCE_MISMATCH"


@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_risk_per_trade: Decimal = Decimal("0.005")  # 0.5%
    max_position_size: Decimal = Decimal("0.10")  # 10%
    max_asset_exposure: Decimal = Decimal("0.25")  # 25%
    max_capital_utilization: Decimal = Decimal("0.60")  # 60%
    daily_loss_limit: Decimal = Decimal("0.02")  # 2%
    weekly_loss_limit: Decimal = Decimal("0.05")  # 5%
    max_drawdown: Decimal = Decimal("0.10")  # 10%
    max_open_positions: int = 5
    stale_data_threshold_minutes: int = 5


@dataclass
class RiskCheckResult:
    """Result of risk check."""
    approved: bool
    risk_level: RiskLevel
    reasons: list[str]
    events: list[RiskEvent]
    adjusted_quantity: Optional[Decimal] = None


class RiskEngine:
    """
    Risk Engine that validates all trading decisions.

    The strategy can only create a trade request.
    The Risk Engine decides whether to execute it.
    """

    def __init__(self, config: RiskConfig = None):
        self.config = config or RiskConfig()
        self.daily_pnl = Decimal("0")
        self.weekly_pnl = Decimal("0")
        self.peak_equity = Decimal("0")
        self.current_equity = Decimal("0")
        self.is_emergency_stop = False
        self.last_data_time: Optional[datetime] = None
        self.consecutive_errors = 0

    def check_trade(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        current_balance: Decimal,
        current_positions: dict,
        total_capital: Decimal,
    ) -> RiskCheckResult:
        """
        Validate a trade request against risk limits.

        Args:
            symbol: Trading pair
            side: 'buy' or 'sell'
            quantity: Requested quantity
            price: Current price
            current_balance: Available balance
            current_positions: Dict of current positions
            total_capital: Total portfolio capital

        Returns:
            RiskCheckResult with approval status
        """
        reasons = []
        events = []
        risk_level = RiskLevel.LOW

        # Check emergency stop
        if self.is_emergency_stop:
            reasons.append("Emergency stop is active")
            events.append(RiskEvent.EMERGENCY_STOP)
            return RiskCheckResult(
                approved=False,
                risk_level=RiskLevel.CRITICAL,
                reasons=reasons,
                events=events,
            )

        # Check stale data
        if self.last_data_time:
            data_age = (datetime.now(timezone.utc) - self.last_data_time).total_seconds() / 60
            if data_age > self.config.stale_data_threshold_minutes:
                reasons.append(f"Data is stale: {data_age:.1f} minutes old")
                events.append(RiskEvent.STALE_DATA)
                risk_level = RiskLevel.HIGH

        # Calculate position value
        position_value = quantity * price
        position_pct = position_value / total_capital if total_capital > 0 else Decimal("0")

        # Check position size limit
        if position_pct > self.config.max_position_size:
            reasons.append(
                f"Position size {position_pct:.2%} exceeds limit {self.config.max_position_size:.2%}"
            )
            events.append(RiskEvent.MAX_POSITION_SIZE)
            risk_level = RiskLevel.HIGH

        # Check asset exposure
        asset_exposure = sum(
            pos.get("value", Decimal("0"))
            for pos in current_positions.values()
            if pos.get("symbol") == symbol
        )
        asset_exposure += position_value
        asset_pct = asset_exposure / total_capital if total_capital > 0 else Decimal("0")

        if asset_pct > self.config.max_asset_exposure:
            reasons.append(
                f"Asset exposure {asset_pct:.2%} exceeds limit {self.config.max_asset_exposure:.2%}"
            )
            events.append(RiskEvent.MAX_ASSET_EXPOSURE)
            risk_level = RiskLevel.HIGH

        # Check capital utilization
        total_position_value = sum(
            pos.get("value", Decimal("0")) for pos in current_positions.values()
        )
        total_position_value += position_value
        utilization = total_position_value / total_capital if total_capital > 0 else Decimal("0")

        if utilization > self.config.max_capital_utilization:
            reasons.append(
                f"Capital utilization {utilization:.2%} exceeds limit {self.config.max_capital_utilization:.2%}"
            )
            events.append(RiskEvent.MAX_CAPITAL_UTILIZATION)
            risk_level = RiskLevel.HIGH

        # Check daily loss limit
        if self.daily_pnl < 0:
            daily_loss_pct = abs(self.daily_pnl) / total_capital if total_capital > 0 else Decimal("0")
            if daily_loss_pct > self.config.daily_loss_limit:
                reasons.append(
                    f"Daily loss {daily_loss_pct:.2%} exceeds limit {self.config.daily_loss_limit:.2%}"
                )
                events.append(RiskEvent.DAILY_LOSS_LIMIT)
                risk_level = RiskLevel.CRITICAL

        # Check weekly loss limit
        if self.weekly_pnl < 0:
            weekly_loss_pct = abs(self.weekly_pnl) / total_capital if total_capital > 0 else Decimal("0")
            if weekly_loss_pct > self.config.weekly_loss_limit:
                reasons.append(
                    f"Weekly loss {weekly_loss_pct:.2%} exceeds limit {self.config.weekly_loss_limit:.2%}"
                )
                events.append(RiskEvent.WEEKLY_LOSS_LIMIT)
                risk_level = RiskLevel.CRITICAL

        # Check drawdown
        if self.peak_equity > 0:
            drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
            if drawdown > self.config.max_drawdown:
                reasons.append(
                    f"Drawdown {drawdown:.2%} exceeds limit {self.config.max_drawdown:.2%}"
                )
                events.append(RiskEvent.MAX_DRAWDOWN)
                risk_level = RiskLevel.CRITICAL

        # Check number of open positions
        if len(current_positions) >= self.config.max_open_positions:
            reasons.append(
                f"Too many open positions: {len(current_positions)} >= {self.config.max_open_positions}"
            )
            risk_level = RiskLevel.MEDIUM

        # Determine approval
        approved = len(reasons) == 0

        # Calculate adjusted quantity if position size too large
        adjusted_quantity = None
        if not approved and position_pct > self.config.max_position_size:
            max_value = total_capital * self.config.max_position_size
            adjusted_quantity = max_value / price
            reasons.append(f"Adjusted quantity to {adjusted_quantity}")

        # Log risk check
        if not approved:
            logger.warning(
                "trade_rejected",
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                risk_level=risk_level.value,
                reasons=reasons,
                events=[e.value for e in events],
            )

        return RiskCheckResult(
            approved=approved,
            risk_level=risk_level,
            reasons=reasons,
            events=events,
            adjusted_quantity=adjusted_quantity,
        )

    def update_pnl(self, daily_pnl: Decimal, weekly_pnl: Decimal):
        """Update PnL for risk calculations."""
        self.daily_pnl = daily_pnl
        self.weekly_pnl = weekly_pnl

    def update_equity(self, equity: Decimal):
        """Update equity and peak equity."""
        self.current_equity = equity
        if equity > self.peak_equity:
            self.peak_equity = equity

    def set_emergency_stop(self, active: bool, reason: str = ""):
        """Activate or deactivate emergency stop."""
        self.is_emergency_stop = active
        if active:
            logger.critical("emergency_stop_activated", reason=reason)
        else:
            logger.info("emergency_stop_deactivated")

    def update_data_time(self, timestamp: datetime):
        """Update last data timestamp."""
        self.last_data_time = timestamp

    def record_error(self):
        """Record a system error."""
        self.consecutive_errors += 1
        if self.consecutive_errors >= 5:
            self.set_emergency_stop(True, "Too many consecutive errors")

    def reset_errors(self):
        """Reset error counter."""
        self.consecutive_errors = 0

    def reset_daily(self):
        """Reset daily PnL (call at start of new day)."""
        self.daily_pnl = Decimal("0")

    def reset_weekly(self):
        """Reset weekly PnL (call at start of new week)."""
        self.weekly_pnl = Decimal("0")
