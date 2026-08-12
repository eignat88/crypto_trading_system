from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterable


def _canonical_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("dataset timestamps must be timezone-aware")
        return value.astimezone(timezone.utc).isoformat()
    return value


def _canonical_candle(candle: dict[str, Any]) -> dict[str, Any]:
    indicators = candle.get("indicators", {})
    return {
        "symbol": str(candle["symbol"]),
        "interval": str(candle["interval"]),
        "open_time": _canonical_scalar(candle["open_time"]),
        "open": _canonical_scalar(candle["open"]),
        "high": _canonical_scalar(candle["high"]),
        "low": _canonical_scalar(candle["low"]),
        "close": _canonical_scalar(candle["close"]),
        "volume": _canonical_scalar(candle["volume"]),
        "ema_20": _canonical_scalar(indicators.get("ema_20")),
        "ema_50": _canonical_scalar(indicators.get("ema_50")),
        "ema_200": _canonical_scalar(indicators.get("ema_200")),
        "rsi": _canonical_scalar(indicators.get("rsi")),
        "atr": _canonical_scalar(indicators.get("atr")),
        "volatility": _canonical_scalar(indicators.get("volatility")),
        "regime": indicators.get("regime"),
        "regime_confidence": _canonical_scalar(indicators.get("regime_confidence")),
    }


def build_dataset_fingerprint(
    candles: Iterable[dict[str, Any]],
    *,
    indicator_model_version: str,
    regime_model_version: str,
) -> str:
    """Hash reproducibility-relevant market/derived data in deterministic order."""
    if not indicator_model_version:
        raise ValueError("indicator_model_version must be non-empty")
    if not regime_model_version:
        raise ValueError("regime_model_version must be non-empty")

    canonical = [_canonical_candle(candle) for candle in candles]
    canonical.sort(key=lambda item: (item["symbol"], item["open_time"]))
    payload = {
        "indicator_model_version": indicator_model_version,
        "regime_model_version": regime_model_version,
        "candles": canonical,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
