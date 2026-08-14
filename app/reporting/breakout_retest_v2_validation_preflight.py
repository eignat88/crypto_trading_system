from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

RESEARCH_EXHAUSTED_END = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
REQUIRED_SYMBOLS = ("BTCUSDT", "ETHUSDT")
REQUIRED_INTERVAL = "1h"
SEGMENT_DAYS = 60
MIN_TEMPORAL_SEGMENTS = 3
MIN_VALIDATION_DURATION = timedelta(days=SEGMENT_DAYS * MIN_TEMPORAL_SEGMENTS)

STATUS_READY = "READY"
STATUS_INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
STATUS_BLOCKED = "BLOCKED"

# Git blob ids frozen before independent validation. Text files are normalized
# to LF before hashing so Windows autocrlf does not create a false mismatch.
FROZEN_GIT_BLOBS: dict[str, str] = {
    "docs/strategy_breakout_retest_v2.md": "54ffc4bebe5017f6f3add26e912a9982ae7f712d",
    "docs/breakout_retest_v2_independent_validation_plan.md": "1531a8789c56c7f7b8c596cf4ef8c0d10c3db201",
    "app/strategies/breakout_retest_v2.py": "099355ff6698fce185e69a8bcd834f1b2e67ca43",
    "app/backtest/backtest_engine.py": "1e623ac4f329d98b96e3e033e45f6387bf505ab6",
    "app/risk/risk_engine.py": "d2336ad0701f6084a253d96fac5d3af0c23e0d48",
    "app/backtest/commission_model.py": "df95f0826d8f9f4bf6f7526fc45c1b59bb92b106",
    "app/backtest/slippage_model.py": "67dc0606fb71b5a641c2d003fbe54e019d21fca9",
}


@dataclass(frozen=True)
class StructuralCandleRecord:
    candle_id: int
    symbol: str
    interval: str
    open_time: datetime
    has_ema20: bool
    has_ema50: bool
    has_ema200: bool
    has_regime: bool


@dataclass(frozen=True)
class SymbolPreflight:
    symbol: str
    candle_count: int
    expected_candle_count: int
    first_open_time: datetime | None
    last_open_time: datetime | None
    gaps: int
    duplicates: int
    missing_ema20: int
    missing_ema50: int
    missing_ema200: int
    missing_regime: int
    coverage_complete: bool
    indicators_ready: bool
    passed: bool


@dataclass(frozen=True)
class IntegrityFingerprint:
    path: str
    expected_git_blob: str
    actual_git_blob: str | None
    sha256: str | None
    matched: bool


@dataclass(frozen=True)
class ValidationPreflightResult:
    status: str
    provenance_id: str
    start: datetime
    end: datetime
    duration_days: int
    temporal_segments: int
    symbols: tuple[SymbolPreflight, ...]
    integrity: tuple[IntegrityFingerprint, ...]
    trade_count_gate: str
    performance_calculated: bool
    strategy_executed: bool
    reasons: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.status == STATUS_READY


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("validation timestamps must be timezone-aware UTC")
    result = value.astimezone(UTC)
    if result.utcoffset() != timedelta(0):
        raise ValueError("validation timestamps must normalize to UTC")
    return result


def validate_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start_utc = _utc(start)
    end_utc = _utc(end)
    if end_utc <= start_utc:
        raise ValueError("validation end must be greater than start")
    if start_utc < RESEARCH_EXHAUSTED_END:
        raise ValueError(
            "validation period overlaps research-exhausted history: "
            f"start={start_utc.isoformat()} exhausted_end={RESEARCH_EXHAUSTED_END.isoformat()}"
        )
    if start_utc.minute or start_utc.second or start_utc.microsecond:
        raise ValueError("validation start must be aligned to an exact UTC hour")
    if end_utc.minute or end_utc.second or end_utc.microsecond:
        raise ValueError("validation end must be aligned to an exact UTC hour")
    return start_utc, end_utc


def _expected_hourly_candles(start: datetime, end: datetime) -> int:
    seconds = int((end - start).total_seconds())
    if seconds % 3600:
        raise ValueError("validation period must contain whole 1h intervals")
    return seconds // 3600


def validate_symbol_records(
    *,
    symbol: str,
    records: Iterable[StructuralCandleRecord],
    start: datetime,
    end: datetime,
) -> SymbolPreflight:
    if symbol not in REQUIRED_SYMBOLS:
        raise ValueError(f"unsupported validation symbol: {symbol}")
    start, end = validate_period(start, end)
    rows = sorted(records, key=lambda item: item.open_time)
    expected = _expected_hourly_candles(start, end)

    gaps = 0
    duplicates = 0
    seen_times: set[datetime] = set()
    previous_time: datetime | None = None
    missing_ema20 = 0
    missing_ema50 = 0
    missing_ema200 = 0
    missing_regime = 0

    for row in rows:
        row_time = _utc(row.open_time)
        if row.symbol != symbol:
            raise ValueError(f"foreign symbol in {symbol} validation records: {row.symbol}")
        if row.interval != REQUIRED_INTERVAL:
            raise ValueError(f"unexpected interval for {symbol}: {row.interval}")
        if not (start <= row_time < end):
            raise ValueError(
                f"record outside validation period for {symbol}: {row_time.isoformat()}"
            )
        if row_time in seen_times:
            duplicates += 1
        seen_times.add(row_time)
        if previous_time is not None:
            delta = row_time - previous_time
            if delta > timedelta(hours=1):
                gaps += int(delta.total_seconds() // 3600) - 1
        previous_time = row_time
        missing_ema20 += int(not row.has_ema20)
        missing_ema50 += int(not row.has_ema50)
        missing_ema200 += int(not row.has_ema200)
        missing_regime += int(not row.has_regime)

    coverage_complete = (
        len(rows) == expected
        and duplicates == 0
        and gaps == 0
        and (not rows or rows[0].open_time.astimezone(UTC) == start)
        and (
            not rows
            or rows[-1].open_time.astimezone(UTC)
            == end - timedelta(hours=1)
        )
    )
    indicators_ready = all(
        value == 0
        for value in (missing_ema20, missing_ema50, missing_ema200, missing_regime)
    )

    return SymbolPreflight(
        symbol=symbol,
        candle_count=len(rows),
        expected_candle_count=expected,
        first_open_time=None if not rows else rows[0].open_time.astimezone(UTC),
        last_open_time=None if not rows else rows[-1].open_time.astimezone(UTC),
        gaps=gaps,
        duplicates=duplicates,
        missing_ema20=missing_ema20,
        missing_ema50=missing_ema50,
        missing_ema200=missing_ema200,
        missing_regime=missing_regime,
        coverage_complete=coverage_complete,
        indicators_ready=indicators_ready,
        passed=coverage_complete and indicators_ready,
    )


def _normalized_repo_bytes(path: Path) -> bytes:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").encode("utf-8")


def _git_blob_sha1(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def fingerprint_frozen_files(repo_root: Path) -> tuple[IntegrityFingerprint, ...]:
    results: list[IntegrityFingerprint] = []
    for relative_path, expected_blob in FROZEN_GIT_BLOBS.items():
        path = repo_root / relative_path
        if not path.is_file():
            results.append(
                IntegrityFingerprint(
                    path=relative_path,
                    expected_git_blob=expected_blob,
                    actual_git_blob=None,
                    sha256=None,
                    matched=False,
                )
            )
            continue
        content = _normalized_repo_bytes(path)
        actual_blob = _git_blob_sha1(content)
        results.append(
            IntegrityFingerprint(
                path=relative_path,
                expected_git_blob=expected_blob,
                actual_git_blob=actual_blob,
                sha256=hashlib.sha256(content).hexdigest(),
                matched=actual_blob == expected_blob,
            )
        )
    return tuple(results)


def dataset_structure_fingerprint(
    records_by_symbol: dict[str, Iterable[StructuralCandleRecord]],
) -> str:
    """Fingerprint only ids/timestamps/readiness flags, never OHLC or PnL data."""
    parts: list[str] = []
    for symbol in sorted(records_by_symbol):
        for row in sorted(records_by_symbol[symbol], key=lambda item: item.open_time):
            parts.append(
                "|".join(
                    (
                        symbol,
                        str(row.candle_id),
                        row.open_time.astimezone(UTC).isoformat(),
                        str(int(row.has_ema20)),
                        str(int(row.has_ema50)),
                        str(int(row.has_ema200)),
                        str(int(row.has_regime)),
                    )
                )
            )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def run_preflight(
    *,
    records_by_symbol: dict[str, Iterable[StructuralCandleRecord]],
    start: datetime,
    end: datetime,
    provenance_id: str,
    repo_root: Path,
) -> ValidationPreflightResult:
    start, end = validate_period(start, end)
    provenance = provenance_id.strip()
    if not provenance:
        raise ValueError("provenance_id is required")

    symbol_results = tuple(
        validate_symbol_records(
            symbol=symbol,
            records=records_by_symbol.get(symbol, ()),
            start=start,
            end=end,
        )
        for symbol in REQUIRED_SYMBOLS
    )
    integrity = fingerprint_frozen_files(repo_root)

    duration = end - start
    duration_days = int(duration.total_seconds() // 86400)
    temporal_segments = duration_days // SEGMENT_DAYS
    reasons: list[str] = []

    if any(not item.matched for item in integrity):
        reasons.append("FROZEN_FILE_INTEGRITY_MISMATCH")
    for item in symbol_results:
        if not item.coverage_complete:
            reasons.append(f"{item.symbol}_DATA_COVERAGE_INCOMPLETE")
        if not item.indicators_ready:
            reasons.append(f"{item.symbol}_FROZEN_INPUTS_NOT_READY")

    if reasons:
        status = STATUS_BLOCKED
    elif duration < MIN_VALIDATION_DURATION or temporal_segments < MIN_TEMPORAL_SEGMENTS:
        status = STATUS_INSUFFICIENT_SAMPLE
        reasons.append("MIN_THREE_60D_TEMPORAL_SEGMENTS_NOT_REACHED")
    else:
        status = STATUS_READY

    return ValidationPreflightResult(
        status=status,
        provenance_id=provenance,
        start=start,
        end=end,
        duration_days=duration_days,
        temporal_segments=temporal_segments,
        symbols=symbol_results,
        integrity=integrity,
        trade_count_gate="PENDING_ONE_SHOT_VALIDATION",
        performance_calculated=False,
        strategy_executed=False,
        reasons=tuple(reasons),
    )
