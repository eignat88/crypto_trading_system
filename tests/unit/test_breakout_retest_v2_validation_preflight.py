from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.reporting.breakout_retest_v2_validation_preflight as preflight
from app.reporting.breakout_retest_v2_validation_preflight import (
    RESEARCH_EXHAUSTED_END,
    STATUS_BLOCKED,
    STATUS_INSUFFICIENT_SAMPLE,
    STATUS_READY,
    StructuralCandleRecord,
    dataset_structure_fingerprint,
    fingerprint_frozen_files,
    run_preflight,
    validate_period,
    validate_symbol_records,
)

UTC = timezone.utc


def _records(symbol: str, start: datetime, hours: int) -> list[StructuralCandleRecord]:
    return [
        StructuralCandleRecord(
            candle_id=(1 if symbol == "BTCUSDT" else 1_000_000) + index,
            symbol=symbol,
            interval="1h",
            open_time=start + timedelta(hours=index),
            has_ema20=True,
            has_ema50=True,
            has_ema200=True,
            has_regime=True,
        )
        for index in range(hours)
    ]


def test_validation_period_cannot_overlap_research_exhausted_history() -> None:
    with pytest.raises(ValueError, match="overlaps research-exhausted"):
        validate_period(
            RESEARCH_EXHAUSTED_END - timedelta(hours=1),
            RESEARCH_EXHAUSTED_END + timedelta(days=180),
        )


def test_exact_180d_complete_sample_is_ready_when_integrity_matches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start = RESEARCH_EXHAUSTED_END
    end = start + timedelta(days=180)
    hours = 180 * 24
    monkeypatch.setattr(preflight, "FROZEN_GIT_BLOBS", {})
    result = run_preflight(
        records_by_symbol={
            "BTCUSDT": _records("BTCUSDT", start, hours),
            "ETHUSDT": _records("ETHUSDT", start, hours),
        },
        start=start,
        end=end,
        provenance_id="future_bybit_dds_v1",
        repo_root=tmp_path,
    )
    assert result.status == STATUS_READY
    assert result.temporal_segments == 3
    assert result.trade_count_gate == "PENDING_ONE_SHOT_VALIDATION"
    assert result.performance_calculated is False
    assert result.strategy_executed is False


def test_shorter_complete_sample_is_insufficient_not_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start = RESEARCH_EXHAUSTED_END
    end = start + timedelta(days=179)
    hours = 179 * 24
    monkeypatch.setattr(preflight, "FROZEN_GIT_BLOBS", {})
    result = run_preflight(
        records_by_symbol={
            "BTCUSDT": _records("BTCUSDT", start, hours),
            "ETHUSDT": _records("ETHUSDT", start, hours),
        },
        start=start,
        end=end,
        provenance_id="future_bybit_dds_v1",
        repo_root=tmp_path,
    )
    assert result.status == STATUS_INSUFFICIENT_SAMPLE
    assert "MIN_THREE_60D_TEMPORAL_SEGMENTS_NOT_REACHED" in result.reasons


def test_gap_or_duplicate_blocks_symbol_coverage() -> None:
    start = RESEARCH_EXHAUSTED_END
    end = start + timedelta(hours=4)
    rows = _records("BTCUSDT", start, 4)
    rows[2] = StructuralCandleRecord(
        **{**rows[2].__dict__, "open_time": rows[1].open_time}
    )
    result = validate_symbol_records(
        symbol="BTCUSDT", records=rows, start=start, end=end
    )
    assert result.duplicates == 1
    assert result.coverage_complete is False
    assert result.passed is False


def test_missing_frozen_input_blocks_preflight(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start = RESEARCH_EXHAUSTED_END
    end = start + timedelta(days=180)
    hours = 180 * 24
    btc = _records("BTCUSDT", start, hours)
    btc[100] = StructuralCandleRecord(**{**btc[100].__dict__, "has_ema20": False})
    monkeypatch.setattr(preflight, "FROZEN_GIT_BLOBS", {})
    result = run_preflight(
        records_by_symbol={"BTCUSDT": btc, "ETHUSDT": _records("ETHUSDT", start, hours)},
        start=start,
        end=end,
        provenance_id="future_bybit_dds_v1",
        repo_root=tmp_path,
    )
    assert result.status == STATUS_BLOCKED
    assert "BTCUSDT_FROZEN_INPUTS_NOT_READY" in result.reasons


def test_frozen_file_integrity_detects_tampering(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "frozen.txt"
    path.write_text("original\n", encoding="utf-8")
    original_bytes = b"original\n"
    expected_blob = preflight._git_blob_sha1(original_bytes)
    monkeypatch.setattr(preflight, "FROZEN_GIT_BLOBS", {"frozen.txt": expected_blob})
    first = fingerprint_frozen_files(tmp_path)
    assert first[0].matched is True
    assert first[0].sha256 is not None

    path.write_text("changed\n", encoding="utf-8")
    second = fingerprint_frozen_files(tmp_path)
    assert second[0].matched is False


def test_dataset_structure_fingerprint_is_deterministic_and_price_free() -> None:
    start = RESEARCH_EXHAUSTED_END
    data = {
        "ETHUSDT": _records("ETHUSDT", start, 3),
        "BTCUSDT": _records("BTCUSDT", start, 3),
    }
    assert dataset_structure_fingerprint(data) == dataset_structure_fingerprint(
        {"BTCUSDT": list(reversed(data["BTCUSDT"])), "ETHUSDT": data["ETHUSDT"]}
    )


def test_preflight_source_does_not_import_or_execute_strategy_or_backtest() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    reporting_source = (
        repo_root / "app/reporting/breakout_retest_v2_validation_preflight.py"
    ).read_text(encoding="utf-8")
    cli_source = (
        repo_root / "scripts/preflight_breakout_retest_v2_validation.py"
    ).read_text(encoding="utf-8")
    combined = reporting_source + "\n" + cli_source

    assert "BreakoutRetestV2Strategy" not in combined
    assert "BreakoutRetestStrategy" not in combined
    assert "BacktestEngine" not in combined
    assert "run_fixed_parameter_walk_forward" not in combined
    assert "open_price" not in cli_source
    assert "high_price" not in cli_source
    assert "low_price" not in cli_source
    assert "close_price" not in cli_source
