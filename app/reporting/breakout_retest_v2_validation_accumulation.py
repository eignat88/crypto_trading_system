from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Iterable

from app.reporting.breakout_retest_v2_validation_preflight import (
    REQUIRED_INTERVAL,
    REQUIRED_SYMBOLS,
    RESEARCH_EXHAUSTED_END,
    StructuralCandleRecord,
)

VALIDATION_START = RESEARCH_EXHAUSTED_END
VALIDATION_END = datetime(2027, 2, 6, 0, 0, tzinfo=timezone.utc)
TARGET_HOURS = int((VALIDATION_END - VALIDATION_START).total_seconds() // 3600)
TARGET_DAYS = int((VALIDATION_END - VALIDATION_START).total_seconds() // 86400)

STATUS_ACCUMULATING = "ACCUMULATING"
STATUS_DATA_QUALITY_BLOCKED = "DATA_QUALITY_BLOCKED"
STATUS_READY_FOR_PREFLIGHT = "READY_FOR_PREFLIGHT"


@dataclass(frozen=True)
class SymbolAccumulationStatus:
    symbol: str
    target_candles: int
    elapsed_expected_candles: int
    actual_candles: int
    completion_pct: str
    first_open_time: datetime | None
    latest_open_time: datetime | None
    gaps: int
    duplicates: int
    missing_ema20: int
    missing_ema50: int
    missing_ema200: int
    missing_regime: int
    elapsed_coverage_complete: bool
    frozen_inputs_ready: bool
    passed_so_far: bool


@dataclass(frozen=True)
class ValidationAccumulationStatus:
    status: str
    as_of: datetime
    validation_start: datetime
    validation_end: datetime
    target_days: int
    elapsed_days: int
    remaining_days: int
    target_candles_per_symbol: int
    elapsed_expected_candles_per_symbol: int
    symbols: tuple[SymbolAccumulationStatus, ...]
    structure_fingerprint: str
    performance_opened: bool
    strategy_executed: bool
    ohlc_loaded: bool
    reasons: tuple[str, ...]

    @property
    def ready_for_preflight(self) -> bool:
        return self.status == STATUS_READY_FOR_PREFLIGHT


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(timezone.utc)


def effective_cutoff(as_of: datetime) -> datetime:
    """Return the exclusive hourly cutoff that is safe to inspect structurally."""
    current = _utc(as_of)
    if current <= VALIDATION_START:
        return VALIDATION_START
    if current >= VALIDATION_END:
        return VALIDATION_END
    # Structural rows are keyed by candle open time. Only hours whose open time
    # is strictly before the current UTC hour are considered elapsed here.
    return current.replace(minute=0, second=0, microsecond=0)


def _expected_elapsed_candles(cutoff: datetime) -> int:
    if cutoff <= VALIDATION_START:
        return 0
    return int((cutoff - VALIDATION_START).total_seconds() // 3600)


def _completion_pct(actual: int) -> str:
    if TARGET_HOURS <= 0:
        return "0.00"
    value = min(max(actual, 0), TARGET_HOURS) * 100 / TARGET_HOURS
    return f"{value:.2f}"


def validate_accumulated_symbol(
    *,
    symbol: str,
    records: Iterable[StructuralCandleRecord],
    cutoff: datetime,
) -> SymbolAccumulationStatus:
    if symbol not in REQUIRED_SYMBOLS:
        raise ValueError(f"unsupported validation symbol: {symbol}")
    cutoff = _utc(cutoff)
    if not (VALIDATION_START <= cutoff <= VALIDATION_END):
        raise ValueError("cutoff must be inside frozen validation range")

    rows = sorted(records, key=lambda row: row.open_time)
    expected = _expected_elapsed_candles(cutoff)
    seen: set[datetime] = set()
    previous: datetime | None = None
    gaps = 0
    duplicates = 0
    missing_ema20 = 0
    missing_ema50 = 0
    missing_ema200 = 0
    missing_regime = 0

    for row in rows:
        timestamp = _utc(row.open_time)
        if row.symbol != symbol:
            raise ValueError(f"foreign symbol in {symbol} accumulation records: {row.symbol}")
        if row.interval != REQUIRED_INTERVAL:
            raise ValueError(f"unexpected interval for {symbol}: {row.interval}")
        if not (VALIDATION_START <= timestamp < cutoff):
            raise ValueError(
                f"record outside elapsed validation prefix for {symbol}: {timestamp.isoformat()}"
            )
        if timestamp in seen:
            duplicates += 1
        seen.add(timestamp)
        if previous is not None:
            delta = timestamp - previous
            if delta > timedelta(hours=1):
                gaps += int(delta.total_seconds() // 3600) - 1
        previous = timestamp
        missing_ema20 += int(not row.has_ema20)
        missing_ema50 += int(not row.has_ema50)
        missing_ema200 += int(not row.has_ema200)
        missing_regime += int(not row.has_regime)

    boundary_ok = True
    if expected > 0:
        boundary_ok = (
            bool(rows)
            and _utc(rows[0].open_time) == VALIDATION_START
            and _utc(rows[-1].open_time) == cutoff - timedelta(hours=1)
        )

    coverage = len(rows) == expected and gaps == 0 and duplicates == 0 and boundary_ok
    inputs_ready = all(
        value == 0
        for value in (missing_ema20, missing_ema50, missing_ema200, missing_regime)
    )

    return SymbolAccumulationStatus(
        symbol=symbol,
        target_candles=TARGET_HOURS,
        elapsed_expected_candles=expected,
        actual_candles=len(rows),
        completion_pct=_completion_pct(len(rows)),
        first_open_time=None if not rows else _utc(rows[0].open_time),
        latest_open_time=None if not rows else _utc(rows[-1].open_time),
        gaps=gaps,
        duplicates=duplicates,
        missing_ema20=missing_ema20,
        missing_ema50=missing_ema50,
        missing_ema200=missing_ema200,
        missing_regime=missing_regime,
        elapsed_coverage_complete=coverage,
        frozen_inputs_ready=inputs_ready,
        passed_so_far=coverage and inputs_ready,
    )


def structure_fingerprint(
    records_by_symbol: dict[str, Iterable[StructuralCandleRecord]],
) -> str:
    parts: list[str] = []
    for symbol in sorted(records_by_symbol):
        for row in sorted(records_by_symbol[symbol], key=lambda item: item.open_time):
            parts.append(
                "|".join(
                    (
                        symbol,
                        str(row.candle_id),
                        _utc(row.open_time).isoformat(),
                        str(int(row.has_ema20)),
                        str(int(row.has_ema50)),
                        str(int(row.has_ema200)),
                        str(int(row.has_regime)),
                    )
                )
            )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def build_accumulation_status(
    *,
    records_by_symbol: dict[str, Iterable[StructuralCandleRecord]],
    as_of: datetime,
) -> ValidationAccumulationStatus:
    as_of_utc = _utc(as_of)
    cutoff = effective_cutoff(as_of_utc)
    symbol_results = tuple(
        validate_accumulated_symbol(
            symbol=symbol,
            records=records_by_symbol.get(symbol, ()),
            cutoff=cutoff,
        )
        for symbol in REQUIRED_SYMBOLS
    )

    elapsed = max(timedelta(0), min(cutoff, VALIDATION_END) - VALIDATION_START)
    elapsed_days = int(elapsed.total_seconds() // 86400)
    remaining_days = max(0, TARGET_DAYS - elapsed_days)
    reasons: list[str] = []

    for item in symbol_results:
        if not item.elapsed_coverage_complete:
            reasons.append(f"{item.symbol}_ELAPSED_COVERAGE_INCOMPLETE")
        if not item.frozen_inputs_ready:
            reasons.append(f"{item.symbol}_FROZEN_INPUTS_NOT_READY")

    if reasons:
        status = STATUS_DATA_QUALITY_BLOCKED
    elif cutoff >= VALIDATION_END:
        status = STATUS_READY_FOR_PREFLIGHT
    else:
        status = STATUS_ACCUMULATING

    return ValidationAccumulationStatus(
        status=status,
        as_of=as_of_utc,
        validation_start=VALIDATION_START,
        validation_end=VALIDATION_END,
        target_days=TARGET_DAYS,
        elapsed_days=elapsed_days,
        remaining_days=remaining_days,
        target_candles_per_symbol=TARGET_HOURS,
        elapsed_expected_candles_per_symbol=_expected_elapsed_candles(cutoff),
        symbols=symbol_results,
        structure_fingerprint=structure_fingerprint(records_by_symbol),
        performance_opened=False,
        strategy_executed=False,
        ohlc_loaded=False,
        reasons=tuple(reasons),
    )
