from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HoldoutSpec:
    name: str
    purpose: str
    strategy_name: str
    strategy_spec_version: str
    implementation_status: str
    symbols: tuple[str, ...]
    exchange: str
    interval: str
    period_start: datetime
    period_end: datetime
    expected_candles_per_symbol: int
    indicator_model_version: str
    regime_model_version: str
    execution_model_version: str
    performance_sealed_until_period_end: bool
    frozen_rules: dict[str, Any]


@dataclass(frozen=True)
class SymbolHoldoutHealth:
    symbol: str
    expected_closed_candles: int
    observed_candles: int
    derived_regimes: int
    duplicate_candles: int
    missing_candles: int
    first_open_time: datetime | None
    last_open_time: datetime | None

    @property
    def healthy(self) -> bool:
        return (
            self.observed_candles == self.expected_closed_candles
            and self.derived_regimes == self.expected_closed_candles
            and self.duplicate_candles == 0
            and self.missing_candles == 0
        )


@dataclass(frozen=True)
class HoldoutStatus:
    state: str
    now: datetime
    cutoff: datetime
    full_period_complete: bool
    performance_access_allowed: bool
    strategy_implementation_ready: bool
    symbols: tuple[SymbolHoldoutHealth, ...]
    reasons: tuple[str, ...]


def _utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.tzinfo is None:
        raise ValueError("Holdout timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def load_holdout_spec(path: Path) -> HoldoutSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    start = _utc(payload["period_start"])
    end = _utc(payload["period_end"])
    if end <= start:
        raise ValueError("period_end must be after period_start")
    if payload["interval"] != "1h":
        raise ValueError("Independent holdout v1 supports only 1h")
    calculated = int((end - start) / timedelta(hours=1))
    expected = int(payload["expected_candles_per_symbol"])
    if calculated != expected:
        raise ValueError(
            f"Holdout candle count mismatch: interval implies {calculated}, config says {expected}"
        )
    return HoldoutSpec(
        name=str(payload["name"]),
        purpose=str(payload["purpose"]),
        strategy_name=str(payload["strategy_name"]),
        strategy_spec_version=str(payload["strategy_spec_version"]),
        implementation_status=str(payload["implementation_status"]),
        symbols=tuple(str(v) for v in payload["symbols"]),
        exchange=str(payload["exchange"]),
        interval=str(payload["interval"]),
        period_start=start,
        period_end=end,
        expected_candles_per_symbol=expected,
        indicator_model_version=str(payload["indicator_model_version"]),
        regime_model_version=str(payload["regime_model_version"]),
        execution_model_version=str(payload["execution_model_version"]),
        performance_sealed_until_period_end=bool(payload["performance_sealed_until_period_end"]),
        frozen_rules=dict(payload["frozen_rules"]),
    )


def completed_candle_cutoff(spec: HoldoutSpec, now: datetime) -> datetime:
    now_utc = _utc(now)
    bounded = min(now_utc, spec.period_end)
    hour = bounded.replace(minute=0, second=0, microsecond=0)
    return max(spec.period_start, hour)


def expected_closed_candles(spec: HoldoutSpec, now: datetime) -> int:
    cutoff = completed_candle_cutoff(spec, now)
    return max(0, min(spec.expected_candles_per_symbol, int((cutoff - spec.period_start) / timedelta(hours=1))))


def assess_holdout(
    spec: HoldoutSpec,
    *,
    now: datetime,
    symbol_health: tuple[SymbolHoldoutHealth, ...],
) -> HoldoutStatus:
    now_utc = _utc(now)
    reasons: list[str] = []
    expected_symbols = set(spec.symbols)
    actual_symbols = {item.symbol for item in symbol_health}
    if expected_symbols != actual_symbols:
        reasons.append(
            f"symbol set mismatch: expected={sorted(expected_symbols)} actual={sorted(actual_symbols)}"
        )

    unhealthy = [item.symbol for item in symbol_health if not item.healthy]
    if unhealthy:
        reasons.append(f"data health failed for: {', '.join(sorted(unhealthy))}")

    full_period_complete = now_utc >= spec.period_end
    if not full_period_complete:
        reasons.append(f"holdout is sealed until {spec.period_end.isoformat()}")

    implementation_ready = spec.implementation_status == "implemented_frozen"
    if not implementation_ready:
        reasons.append(
            f"strategy implementation is not frozen/ready: {spec.implementation_status}"
        )

    data_healthy = not unhealthy and expected_symbols == actual_symbols
    performance_access_allowed = (
        full_period_complete
        and data_healthy
        and implementation_ready
        and spec.performance_sealed_until_period_end
    )

    if not full_period_complete:
        state = "COLLECTING_DATA"
    elif not data_healthy:
        state = "BLOCKED_DATA_QUALITY"
    elif not implementation_ready:
        state = "BLOCKED_STRATEGY_IMPLEMENTATION"
    else:
        state = "READY_TO_OPEN"

    return HoldoutStatus(
        state=state,
        now=now_utc,
        cutoff=completed_candle_cutoff(spec, now_utc),
        full_period_complete=full_period_complete,
        performance_access_allowed=performance_access_allowed,
        strategy_implementation_ready=implementation_ready,
        symbols=symbol_health,
        reasons=tuple(reasons),
    )
