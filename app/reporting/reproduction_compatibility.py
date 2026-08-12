from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReproductionBaseline:
    indicator_model_version: str
    regime_model_version: str
    execution_model_version: str
    dataset_fingerprint: str | None = None


@dataclass(frozen=True)
class CompatibilityResult:
    compatible: bool
    reasons: tuple[str, ...]


def check_baseline_compatibility(
    expected: ReproductionBaseline,
    actual: ReproductionBaseline,
) -> CompatibilityResult:
    reasons: list[str] = []
    for field_name in (
        "indicator_model_version",
        "regime_model_version",
        "execution_model_version",
    ):
        expected_value = getattr(expected, field_name)
        actual_value = getattr(actual, field_name)
        if expected_value != actual_value:
            reasons.append(
                f"{field_name} mismatch: expected={expected_value} actual={actual_value}"
            )

    if expected.dataset_fingerprint is None:
        reasons.append("frozen baseline has no dataset_fingerprint")
    elif expected.dataset_fingerprint != actual.dataset_fingerprint:
        reasons.append(
            "dataset_fingerprint mismatch: "
            f"expected={expected.dataset_fingerprint} actual={actual.dataset_fingerprint}"
        )

    return CompatibilityResult(compatible=not reasons, reasons=tuple(reasons))
