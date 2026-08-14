from datetime import UTC, datetime

import pytest

from app.reporting.holdout_validation import (
    SymbolDataHealth,
    evaluate_open_gate,
    expected_completed_candles,
    holdout_from_dict,
)


def _definition():
    return holdout_from_dict(
        {
            "validation_id": "holdout-v2",
            "purpose": "independent prospective validation",
            "strategy_name": "BreakoutRetest",
            "parameters_version": "breakout_retest_v2",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "exchange": "bybit",
            "interval": "1h",
            "period_start": "2026-08-10T00:00:00+00:00",
            "period_end": "2027-02-06T00:00:00+00:00",
            "unlock_at": "2027-02-06T00:00:00+00:00",
            "indicator_model_version": "ind-v2",
            "regime_model_version": "reg-v2",
            "execution_model_version": "engine-v1",
            "strategy_implementation_required_for_open": True,
        }
    )


def test_holdout_is_sealed_before_unlock_even_if_strategy_exists():
    gate = evaluate_open_gate(
        _definition(),
        now=datetime(2026, 8, 12, 13, 0, tzinfo=UTC),
        strategy_implemented=True,
    )
    assert gate.opened is False
    assert gate.reason.startswith("HOLDOUT_SEALED")


def test_holdout_remains_blocked_after_unlock_without_frozen_strategy():
    gate = evaluate_open_gate(
        _definition(),
        now=datetime(2027, 2, 6, 0, 0, tzinfo=UTC),
        strategy_implemented=False,
    )
    assert gate.opened is False
    assert gate.reason.startswith("HOLDOUT_BLOCKED")


def test_holdout_opens_only_after_date_and_strategy_implementation():
    gate = evaluate_open_gate(
        _definition(),
        now=datetime(2027, 2, 6, 0, 0, tzinfo=UTC),
        strategy_implemented=True,
    )
    assert gate.opened is True
    assert gate.reason == "HOLDOUT_OPEN"


def test_expected_completed_candles_floors_partial_hour():
    count = expected_completed_candles(
        _definition(),
        now=datetime(2026, 8, 12, 13, 59, 59, tzinfo=UTC),
    )
    assert count == 61


def test_full_holdout_has_4320_hourly_candles():
    count = expected_completed_candles(
        _definition(),
        now=datetime(2027, 2, 7, 0, 0, tzinfo=UTC),
    )
    assert count == 4320


def test_naive_now_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        expected_completed_candles(
            _definition(),
            now=datetime(2026, 8, 12, 13, 0),
        )


def test_data_health_requires_exact_complete_derived_coverage():
    health = SymbolDataHealth(
        symbol="BTCUSDT",
        expected_candles=61,
        candle_count=61,
        missing_intervals=0,
        duplicate_intervals=0,
        invalid_candles=0,
        indicator_complete_candles=61,
        regime_complete_candles=60,
    )
    assert health.healthy is False
