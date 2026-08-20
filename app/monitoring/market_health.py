"""Staleness and candle-gap monitoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class MarketHealthStatus(StrEnum):
    OK = "OK"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class MarketHealthResult:
    status: MarketHealthStatus
    lag_seconds: float
    missing_intervals: int
    trading_enabled: bool


class MarketHealthMonitor:
    def __init__(
        self,
        *,
        warning_after: timedelta = timedelta(minutes=5),
        critical_after: timedelta = timedelta(minutes=15),
    ) -> None:
        if warning_after >= critical_after:
            raise ValueError("warning threshold must be below critical threshold")
        self.warning_after = warning_after
        self.critical_after = critical_after
        self._last_candle: dict[tuple[str, str], datetime] = {}

    def check(
        self,
        symbol: str,
        interval: str,
        candle_time: datetime,
        *,
        received_at: datetime | None = None,
        expected_interval: timedelta | None = None,
    ) -> MarketHealthResult:
        now = received_at or datetime.now(UTC)
        if candle_time.tzinfo is None or now.tzinfo is None:
            raise ValueError("market timestamps must be timezone-aware")
        lag = max(0.0, (now - candle_time).total_seconds())
        key = (symbol, interval)
        missing = 0
        previous = self._last_candle.get(key)
        if previous is not None and expected_interval and expected_interval.total_seconds() > 0:
            missing = max(0, int((candle_time - previous) / expected_interval) - 1)
        if previous is None or candle_time > previous:
            self._last_candle[key] = candle_time
        if lag > self.critical_after.total_seconds() or missing:
            status = MarketHealthStatus.CRITICAL
        elif lag >= self.warning_after.total_seconds():
            status = MarketHealthStatus.WARNING
        else:
            status = MarketHealthStatus.OK
        return MarketHealthResult(status, lag, missing, status is not MarketHealthStatus.CRITICAL)
