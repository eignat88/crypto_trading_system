from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.reporting.holdout_validation import (
    SymbolHoldoutHealth,
    assess_holdout,
    expected_closed_candles,
    load_holdout_spec,
)

SPEC_PATH = Path("config/validation/breakout_retest_v2_holdout.json")


def _healthy(symbol: str, count: int) -> SymbolHoldoutHealth:
    return SymbolHoldoutHealth(
        symbol=symbol,
        expected_closed_candles=count,
        observed_candles=count,
        derived_regimes=count,
        duplicate_candles=0,
        missing_candles=0,
        first_open_time=None,
        last_open_time=None,
    )


def test_holdout_spec_is_exactly_180_days_4320_hours():
    spec = load_holdout_spec(SPEC_PATH)
    assert spec.expected_candles_per_symbol == 4320
    assert spec.period_start.isoformat() == "2026-08-10T00:00:00+00:00"
    assert spec.period_end.isoformat() == "2027-02-06T00:00:00+00:00"


def test_expected_closed_candles_ignores_current_incomplete_hour():
    spec = load_holdout_spec(SPEC_PATH)
    now = datetime(2026, 8, 12, 12, 21, tzinfo=timezone.utc)
    assert expected_closed_candles(spec, now) == 60


def test_pre_end_holdout_remains_sealed_even_with_healthy_data():
    spec = load_holdout_spec(SPEC_PATH)
    now = datetime(2026, 8, 12, 12, 21, tzinfo=timezone.utc)
    count = expected_closed_candles(spec, now)
    status = assess_holdout(
        spec,
        now=now,
        symbol_health=tuple(_healthy(symbol, count) for symbol in spec.symbols),
    )
    assert status.state == "COLLECTING_DATA"
    assert status.performance_access_allowed is False


def test_completed_holdout_blocks_when_data_has_gap():
    spec = replace(load_holdout_spec(SPEC_PATH), implementation_status="implemented_frozen")
    now = spec.period_end
    health = (
        _healthy("BTCUSDT", 4320),
        replace(_healthy("ETHUSDT", 4320), observed_candles=4319, missing_candles=1),
    )
    status = assess_holdout(spec, now=now, symbol_health=health)
    assert status.state == "BLOCKED_DATA_QUALITY"
    assert status.performance_access_allowed is False


def test_completed_healthy_holdout_blocks_unimplemented_strategy():
    spec = load_holdout_spec(SPEC_PATH)
    now = spec.period_end
    health = tuple(_healthy(symbol, 4320) for symbol in spec.symbols)
    status = assess_holdout(spec, now=now, symbol_health=health)
    assert status.state == "BLOCKED_STRATEGY_IMPLEMENTATION"
    assert status.performance_access_allowed is False


def test_completed_healthy_holdout_opens_only_for_frozen_implementation():
    spec = replace(load_holdout_spec(SPEC_PATH), implementation_status="implemented_frozen")
    now = spec.period_end
    health = tuple(_healthy(symbol, 4320) for symbol in spec.symbols)
    status = assess_holdout(spec, now=now, symbol_health=health)
    assert status.state == "READY_TO_OPEN"
    assert status.performance_access_allowed is True
