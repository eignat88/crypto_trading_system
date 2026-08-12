from app.reporting.reproduction_compatibility import (
    ReproductionBaseline,
    check_baseline_compatibility,
)


def _baseline(**overrides: str | None) -> ReproductionBaseline:
    values = {
        "indicator_model_version": "ind-v2",
        "regime_model_version": "reg-v2",
        "execution_model_version": "engine-v1",
        "dataset_fingerprint": "dataset-a",
    }
    values.update(overrides)
    return ReproductionBaseline(**values)


def test_compatible_baselines_pass():
    result = check_baseline_compatibility(_baseline(), _baseline())
    assert result.compatible is True
    assert result.reasons == ()


def test_model_version_mismatch_blocks_gate():
    result = check_baseline_compatibility(
        _baseline(),
        _baseline(regime_model_version="reg-v3"),
    )
    assert result.compatible is False
    assert any("regime_model_version mismatch" in reason for reason in result.reasons)


def test_missing_frozen_dataset_fingerprint_blocks_gate():
    result = check_baseline_compatibility(
        _baseline(dataset_fingerprint=None),
        _baseline(),
    )
    assert result.compatible is False
    assert "frozen baseline has no dataset_fingerprint" in result.reasons
