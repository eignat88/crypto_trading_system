"""Scoring system for setup signals with configurable weights."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.setups.base import Direction, SetupSignal, SetupType


@dataclass
class ScoringWeights:
    """Configurable scoring weights."""
    setup_base: dict[str, int] = field(default_factory=lambda: {
        "RETEST_READY": 3,
        "FAILED_BREAKOUT": 3,
        "BREAKOUT": 2,
        "COMPRESSION": 2,
    })
    ema_trend_alignment: int = 2
    volume_spike: int = 2
    atr_compression: int = 1
    btc_regime_alignment: int = 1
    excessive_volatility_penalty: int = -2
    low_liquidity_penalty: int = -3
    volume_spike_multiplier: Decimal = field(default_factory=lambda: Decimal("1.5"))
    excessive_volatility_threshold: Decimal = field(default_factory=lambda: Decimal("0.8"))


DEFAULT_WEIGHTS = ScoringWeights()


def calculate_score(
    signal: SetupSignal,
    indicators: dict[str, Any] | None = None,
    btc_regime: str | None = None,
    weights: ScoringWeights | None = None,
) -> Decimal:
    """Calculate score for a setup signal."""
    if weights is None:
        weights = DEFAULT_WEIGHTS

    score = Decimal(str(weights.setup_base.get(signal.setup_type.value, 0)))

    if indicators is None:
        return score

    ema50 = indicators.get("ema50")
    ema200 = indicators.get("ema200")
    if ema50 is not None and ema200 is not None:
        ema50 = Decimal(str(ema50))
        ema200 = Decimal(str(ema200))
        if signal.direction in (Direction.LONG, Direction.LONG_CANDIDATE):
            if ema50 > ema200:
                score += Decimal(weights.ema_trend_alignment)
        elif signal.direction in (Direction.SHORT, Direction.SHORT_CANDIDATE):
            if ema50 < ema200:
                score += Decimal(weights.ema_trend_alignment)

    volume = indicators.get("volume")
    volume_ma20 = indicators.get("volume_ma20")
    if volume is not None and volume_ma20 is not None:
        volume = Decimal(str(volume))
        volume_ma20 = Decimal(str(volume_ma20))
        if volume_ma20 > 0 and volume / volume_ma20 >= weights.volume_spike_multiplier:
            score += Decimal(weights.volume_spike)

    if btc_regime is not None:
        if signal.direction in (Direction.LONG, Direction.LONG_CANDIDATE):
            if btc_regime in ("TREND_UP", "bull"):
                score += Decimal(weights.btc_regime_alignment)
        elif signal.direction in (Direction.SHORT, Direction.SHORT_CANDIDATE):
            if btc_regime in ("TREND_DOWN", "bear"):
                score += Decimal(weights.btc_regime_alignment)

    return score


def rank_signals(signals: list[SetupSignal]) -> list[SetupSignal]:
    """Sort signals by score descending."""
    return sorted(signals, key=lambda s: s.score, reverse=True)
