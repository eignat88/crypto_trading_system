from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

from app.backtest.dataset_fingerprint import build_dataset_fingerprint


def _candles() -> list[dict]:
    return [
        {
            "symbol": "BTCUSDT",
            "interval": "1h",
            "open_time": datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc),
            "open": Decimal("100"),
            "high": Decimal("101"),
            "low": Decimal("99"),
            "close": Decimal("100.5"),
            "volume": Decimal("10"),
            "indicators": {
                "ema_20": Decimal("100.1"),
                "ema_50": Decimal("99.9"),
                "ema_200": Decimal("98.0"),
                "rsi": Decimal("55"),
                "atr": Decimal("2"),
                "volatility": Decimal("0.4"),
                "regime": "TREND_UP",
                "regime_confidence": Decimal("0.8"),
            },
        }
    ]


def test_dataset_fingerprint_is_deterministic():
    first = build_dataset_fingerprint(
        _candles(),
        indicator_model_version="ind-v2",
        regime_model_version="reg-v2",
    )
    second = build_dataset_fingerprint(
        _candles(),
        indicator_model_version="ind-v2",
        regime_model_version="reg-v2",
    )
    assert first == second


def test_dataset_fingerprint_changes_when_derived_value_changes():
    first_candles = _candles()
    second_candles = deepcopy(first_candles)
    second_candles[0]["indicators"]["regime"] = "RANGE"
    first = build_dataset_fingerprint(
        first_candles,
        indicator_model_version="ind-v2",
        regime_model_version="reg-v2",
    )
    second = build_dataset_fingerprint(
        second_candles,
        indicator_model_version="ind-v2",
        regime_model_version="reg-v2",
    )
    assert first != second


def test_dataset_fingerprint_changes_when_model_version_changes():
    candles = _candles()
    first = build_dataset_fingerprint(
        candles,
        indicator_model_version="ind-v2",
        regime_model_version="reg-v2",
    )
    second = build_dataset_fingerprint(
        candles,
        indicator_model_version="ind-v3",
        regime_model_version="reg-v2",
    )
    assert first != second
