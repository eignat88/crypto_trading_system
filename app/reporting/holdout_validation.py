from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class HoldoutDefinition:
    validation_id: str
    purpose: str
    strategy_name: str
    parameters_version: str
    symbols: tuple[str, ...]
    exchange: str
    interval: str
    period_start: datetime
    period_end: datetime
    unlock_at: datetime
    indicator_model_version: str
    regime_model_version: str
    execution_model_version: str
    strategy_implementation_required_for_open: bool


@dataclass(frozen=True)
class HoldoutGate:
    opened: bool
    reason: str


@dataclass(frozen=True)
class SymbolDataHealth:
    symbol: str
    expected_candles: int
    candle_count: int
    missing_intervals: int
    duplicate_intervals: int
    invalid_candles: int
    indicator_complete_candles: int
    regime_complete_candles: int

    @property
    def healthy(self) -> bool:
        return (
            self.candle_count == self.expected_candles
            and self.missing_intervals == 0
            and self.duplicate_intervals == 0
            and self.invalid_candles == 0
            and self.indicator_complete_candles == self.candle_count
            and self.regime_complete_candles == self.candle_count
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("holdout timestamps must be timezone-aware")
    return value.astimezone(UTC)


def holdout_from_dict(payload: dict[str, Any]) -> HoldoutDefinition:
    return HoldoutDefinition(
        validation_id=str(payload["validation_id"]),
        purpose=str(payload["purpose"]),
        strategy_name=str(payload["strategy_name"]),
        parameters_version=str(payload["parameters_version"]),
        symbols=tuple(str(v) for v in payload["symbols"]),
        exchange=str(payload["exchange"]),
        interval=str(payload["interval"]),
        period_start=_utc(datetime.fromisoformat(str(payload["period_start"]))),
        period_end=_utc(datetime.fromisoformat(str(payload["period_end"]))),
        unlock_at=_utc(datetime.fromisoformat(str(payload["unlock_at"]))),
        indicator_model_version=str(payload["indicator_model_version"]),
        regime_model_version=str(payload["regime_model_version"]),
        execution_model_version=str(payload["execution_model_version"]),
        strategy_implementation_required_for_open=bool(
            payload.get("strategy_implementation_required_for_open", True)
        ),
    )


def evaluate_open_gate(
    definition: HoldoutDefinition,
    *,
    now: datetime,
    strategy_implemented: bool,
) -> HoldoutGate:
    current = _utc(now)
    if current < definition.unlock_at:
        return HoldoutGate(
            opened=False,
            reason=(
                "HOLDOUT_SEALED: performance access is blocked until "
                f"{definition.unlock_at.isoformat()}"
            ),
        )
    if definition.strategy_implementation_required_for_open and not strategy_implemented:
        return HoldoutGate(
            opened=False,
            reason="HOLDOUT_BLOCKED: frozen strategy implementation is not available",
        )
    return HoldoutGate(opened=True, reason="HOLDOUT_OPEN")


def completed_interval_end(
    definition: HoldoutDefinition,
    *,
    now: datetime,
) -> datetime:
    current = min(_utc(now), definition.period_end)
    if definition.interval != "1h":
        raise ValueError(f"unsupported holdout interval: {definition.interval}")
    floored = current.replace(minute=0, second=0, microsecond=0)
    return max(definition.period_start, floored)


def expected_completed_candles(
    definition: HoldoutDefinition,
    *,
    now: datetime,
) -> int:
    end = completed_interval_end(definition, now=now)
    seconds = int((end - definition.period_start).total_seconds())
    return max(0, seconds // 3600)
