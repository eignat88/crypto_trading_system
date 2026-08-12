from copy import deepcopy

from app.reporting.engineering_baseline import (
    baseline_from_dict,
    baseline_to_dict,
    compare_engineering_baselines,
)


def _payload() -> dict:
    return {
        "strategy_name": "BreakoutRetest",
        "parameters_version": "breakout_retest_v1",
        "interval": "1h",
        "period_start": "2024-08-10T00:00:00+00:00",
        "period_end": "2026-08-10T00:00:00+00:00",
        "random_seed": 42,
        "indicator_model_version": "indicators_v2_hourly_volatility",
        "regime_model_version": "regime_v2_hourly_volatility",
        "execution_model_version": "backtest_hardened_v1",
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "candle_count": 17520,
                "dataset_fingerprint": "btc-dataset",
                "total_trades": 49,
                "total_pnl": "-0.33",
                "profitable_windows": 5,
                "audit_fingerprints": ["a", "b"],
            },
            {
                "symbol": "ETHUSDT",
                "candle_count": 17520,
                "dataset_fingerprint": "eth-dataset",
                "total_trades": 63,
                "total_pnl": "-4.59",
                "profitable_windows": 3,
                "audit_fingerprints": ["c", "d"],
            },
        ],
    }


def test_baseline_round_trip_is_lossless():
    baseline = baseline_from_dict(_payload())
    assert baseline_to_dict(baseline) == _payload()


def test_identical_engineering_baselines_pass():
    baseline = baseline_from_dict(_payload())
    result = compare_engineering_baselines(baseline, baseline)
    assert result.compatible is True
    assert result.reasons == ()


def test_dataset_fingerprint_change_fails_before_silent_reproduction():
    expected_payload = _payload()
    actual_payload = deepcopy(expected_payload)
    actual_payload["symbols"][0]["dataset_fingerprint"] = "changed"

    result = compare_engineering_baselines(
        baseline_from_dict(expected_payload),
        baseline_from_dict(actual_payload),
    )
    assert result.compatible is False
    assert any("BTCUSDT.dataset_fingerprint mismatch" in reason for reason in result.reasons)


def test_execution_model_change_fails():
    expected_payload = _payload()
    actual_payload = deepcopy(expected_payload)
    actual_payload["execution_model_version"] = "backtest_hardened_v2"

    result = compare_engineering_baselines(
        baseline_from_dict(expected_payload),
        baseline_from_dict(actual_payload),
    )
    assert result.compatible is False
    assert any("execution_model_version mismatch" in reason for reason in result.reasons)


def test_metric_or_window_audit_change_fails():
    expected_payload = _payload()
    actual_payload = deepcopy(expected_payload)
    actual_payload["symbols"][1]["total_trades"] = 64
    actual_payload["symbols"][1]["audit_fingerprints"][0] = "changed-audit"

    result = compare_engineering_baselines(
        baseline_from_dict(expected_payload),
        baseline_from_dict(actual_payload),
    )
    assert result.compatible is False
    assert any("ETHUSDT.total_trades mismatch" in reason for reason in result.reasons)
    assert any("ETHUSDT.audit_fingerprints mismatch" in reason for reason in result.reasons)
