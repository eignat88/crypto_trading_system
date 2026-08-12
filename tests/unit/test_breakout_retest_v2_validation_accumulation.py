from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.reporting.breakout_retest_v2_validation_accumulation import (
    STATUS_ACCUMULATING,
    STATUS_DATA_QUALITY_BLOCKED,
    STATUS_READY_FOR_PREFLIGHT,
    TARGET_HOURS,
    VALIDATION_END,
    VALIDATION_START,
    build_accumulation_status,
    effective_cutoff,
)
from app.reporting.breakout_retest_v2_validation_preflight import StructuralCandleRecord


def _rows(symbol: str, start: datetime, count: int, *, missing_ema20_at: int | None = None):
    return [
        StructuralCandleRecord(
            candle_id=index + 1,
            symbol=symbol,
            interval="1h",
            open_time=start + timedelta(hours=index),
            has_ema20=index != missing_ema20_at,
            has_ema50=True,
            has_ema200=True,
            has_regime=True,
        )
        for index in range(count)
    ]


def test_before_validation_start_is_clean_zero_progress() -> None:
    status = build_accumulation_status(
        records_by_symbol={"BTCUSDT": [], "ETHUSDT": []},
        as_of=VALIDATION_START - timedelta(hours=1),
    )
    assert status.status == STATUS_ACCUMULATING
    assert status.elapsed_expected_candles_per_symbol == 0
    assert status.elapsed_days == 0
    assert status.remaining_days == 180
    assert all(item.passed_so_far for item in status.symbols)


def test_elapsed_prefix_complete_is_accumulating_not_blocked() -> None:
    as_of = VALIDATION_START + timedelta(hours=10, minutes=37)
    rows = {
        symbol: _rows(symbol, VALIDATION_START, 10)
        for symbol in ("BTCUSDT", "ETHUSDT")
    }
    status = build_accumulation_status(records_by_symbol=rows, as_of=as_of)
    assert status.status == STATUS_ACCUMULATING
    assert status.elapsed_expected_candles_per_symbol == 10
    assert all(item.actual_candles == 10 for item in status.symbols)
    assert all(item.passed_so_far for item in status.symbols)


def test_elapsed_prefix_gap_blocks_status() -> None:
    as_of = VALIDATION_START + timedelta(hours=4)
    btc = _rows("BTCUSDT", VALIDATION_START, 4)
    btc.pop(1)
    eth = _rows("ETHUSDT", VALIDATION_START, 4)
    status = build_accumulation_status(
        records_by_symbol={"BTCUSDT": btc, "ETHUSDT": eth},
        as_of=as_of,
    )
    assert status.status == STATUS_DATA_QUALITY_BLOCKED
    assert "BTCUSDT_ELAPSED_COVERAGE_INCOMPLETE" in status.reasons


def test_missing_frozen_input_blocks_status() -> None:
    as_of = VALIDATION_START + timedelta(hours=3)
    status = build_accumulation_status(
        records_by_symbol={
            "BTCUSDT": _rows("BTCUSDT", VALIDATION_START, 3, missing_ema20_at=1),
            "ETHUSDT": _rows("ETHUSDT", VALIDATION_START, 3),
        },
        as_of=as_of,
    )
    assert status.status == STATUS_DATA_QUALITY_BLOCKED
    assert "BTCUSDT_FROZEN_INPUTS_NOT_READY" in status.reasons


def test_full_target_is_ready_for_preflight() -> None:
    records = {
        symbol: _rows(symbol, VALIDATION_START, TARGET_HOURS)
        for symbol in ("BTCUSDT", "ETHUSDT")
    }
    status = build_accumulation_status(records_by_symbol=records, as_of=VALIDATION_END)
    assert status.status == STATUS_READY_FOR_PREFLIGHT
    assert status.ready_for_preflight
    assert status.elapsed_days == 180
    assert status.remaining_days == 0
    assert all(item.completion_pct == "100.00" for item in status.symbols)


def test_future_rows_outside_elapsed_prefix_fail_closed() -> None:
    as_of = VALIDATION_START + timedelta(hours=2)
    with pytest.raises(ValueError, match="outside elapsed validation prefix"):
        build_accumulation_status(
            records_by_symbol={
                "BTCUSDT": _rows("BTCUSDT", VALIDATION_START, 3),
                "ETHUSDT": _rows("ETHUSDT", VALIDATION_START, 2),
            },
            as_of=as_of,
        )


def test_structure_fingerprint_is_deterministic_without_market_prices() -> None:
    as_of = VALIDATION_START + timedelta(hours=2)
    records = {
        "BTCUSDT": _rows("BTCUSDT", VALIDATION_START, 2),
        "ETHUSDT": _rows("ETHUSDT", VALIDATION_START, 2),
    }
    first = build_accumulation_status(records_by_symbol=records, as_of=as_of)
    second = build_accumulation_status(records_by_symbol=records, as_of=as_of)
    assert first.structure_fingerprint == second.structure_fingerprint
    assert first.performance_opened is False
    assert first.strategy_executed is False
    assert first.ohlc_loaded is False


def test_cli_source_does_not_select_ohlc_or_import_strategy_engine() -> None:
    source = Path("scripts/report_breakout_retest_v2_validation_accumulation.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "BreakoutRetestV2Strategy",
        "BreakoutRetestStrategy",
        "BacktestEngine",
        "run_fixed_parameter_walk_forward",
        "c.open_price",
        "c.high_price",
        "c.low_price",
        "c.close_price",
        "total_pnl",
        "profit_factor",
    )
    for token in forbidden:
        assert token not in source
    assert "c.open_time" in source
    assert "has_ema20" in source


def test_effective_cutoff_is_hour_aligned_and_capped() -> None:
    current = VALIDATION_START + timedelta(hours=5, minutes=59)
    assert effective_cutoff(current) == VALIDATION_START + timedelta(hours=5)
    assert effective_cutoff(VALIDATION_END + timedelta(days=5)) == VALIDATION_END
