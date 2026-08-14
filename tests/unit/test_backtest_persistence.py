from copy import deepcopy
from datetime import UTC, datetime

import pytest

from app.backtest.persistence import (
    _as_utc_datetime,
    build_run_fingerprint,
    run_id_from_fingerprint,
)


def _payload() -> dict:
    return {
        "metadata": {
            "created_at": "2026-08-10T12:00:00+00:00",
            "git_commit": "abc123",
            "exchange": "bybit",
            "symbol": "BTCUSDT",
            "interval": "1h",
            "start": "2026-07-01T00:00:00Z",
            "end": "2026-08-10T00:00:00Z",
            "candle_count": 960,
            "random_seed": 42,
            "dataset_fingerprint": "dataset-a",
            "indicator_model_version": "indicators-v2",
            "regime_model_version": "regime-v2",
            "execution_model_version": "engine-v1",
        },
        "strategy": {
            "name": "TrendDCA",
            "parameters": {
                "parameters_version": "trend_dca_v1",
                "rsi_entry_threshold": "45",
            },
        },
        "configuration": {
            "initial_balance": "500",
            "random_seed": 42,
            "commission": {"taker_fee": "0.001"},
            "slippage": {"fixed_slippage": "0.0005"},
        },
        "backtest": {
            "initial_balance": "500",
            "final_equity": "499.5",
            "total_pnl": "-0.5",
        },
        "audit": {
            "signals": [],
            "risk_decisions": [],
            "orders": [],
            "fills": [],
        },
    }


def test_fingerprint_ignores_runtime_timestamp_and_results():
    first = _payload()
    second = deepcopy(first)
    second["metadata"]["created_at"] = "2026-08-11T12:00:00+00:00"
    second["backtest"]["final_equity"] = "999"
    second["backtest"]["total_pnl"] = "499"
    assert build_run_fingerprint(first) == build_run_fingerprint(second)


def test_fingerprint_changes_when_execution_configuration_changes():
    first = _payload()
    second = deepcopy(first)
    second["configuration"]["slippage"]["fixed_slippage"] = "0.001"
    assert build_run_fingerprint(first) != build_run_fingerprint(second)


def test_fingerprint_changes_when_dataset_changes():
    first = _payload()
    second = deepcopy(first)
    second["metadata"]["dataset_fingerprint"] = "dataset-b"
    assert build_run_fingerprint(first) != build_run_fingerprint(second)


def test_fingerprint_changes_when_model_version_changes():
    first = _payload()
    second = deepcopy(first)
    second["metadata"]["regime_model_version"] = "regime-v3"
    assert build_run_fingerprint(first) != build_run_fingerprint(second)


def test_fingerprint_requires_dataset_metadata():
    payload = _payload()
    del payload["metadata"]["dataset_fingerprint"]
    with pytest.raises(ValueError, match="dataset_fingerprint"):
        build_run_fingerprint(payload)


def test_run_id_is_deterministic_for_same_fingerprint():
    fingerprint = build_run_fingerprint(_payload())
    assert run_id_from_fingerprint(fingerprint) == run_id_from_fingerprint(fingerprint)


def test_as_utc_datetime_parses_z_suffix():
    result = _as_utc_datetime("2026-08-10T12:02:50.532733Z")
    assert result == datetime(2026, 8, 10, 12, 2, 50, 532733, tzinfo=UTC)


def test_as_utc_datetime_converts_offset_to_utc():
    result = _as_utc_datetime("2026-08-10T15:02:50+03:00")
    assert result == datetime(2026, 8, 10, 12, 2, 50, tzinfo=UTC)


def test_as_utc_datetime_treats_naive_datetime_as_utc():
    result = _as_utc_datetime(datetime(2026, 8, 10, 12, 2, 50))
    assert result == datetime(2026, 8, 10, 12, 2, 50, tzinfo=UTC)
