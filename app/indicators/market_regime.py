from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from app.indicators.ema import calculate_ema, calculate_ema_slope
from app.indicators.atr import calculate_atr, calculate_atr_percentage
from app.indicators.volatility import calculate_historical_volatility, calculate_volatility_regime


class MarketRegime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


@dataclass
class RegimeResult:
    regime: MarketRegime
    confidence: Decimal
    reasons: list[str]
    ema_20: Optional[Decimal] = None
    ema_50: Optional[Decimal] = None
    ema_200: Optional[Decimal] = None
    atr_percentage: Optional[Decimal] = None
    volatility: Optional[Decimal] = None


class MarketRegimeDetector:
    """Detects current market regime based on indicators."""

    def __init__(
        self,
        ema_short_period: int = 20,
        ema_medium_period: int = 50,
        ema_long_period: int = 200,
        atr_period: int = 14,
        volatility_period: int = 20,
        high_volatility_threshold: Decimal = Decimal("0.8"),
        range_distance_threshold: Decimal = Decimal("0.02"),
        slope_threshold: Decimal = Decimal("0.001"),
    ):
        self.ema_short_period = ema_short_period
        self.ema_medium_period = ema_medium_period
        self.ema_long_period = ema_long_period
        self.atr_period = atr_period
        self.volatility_period = volatility_period
        self.high_volatility_threshold = high_volatility_threshold
        self.range_distance_threshold = range_distance_threshold
        self.slope_threshold = slope_threshold

    def detect(
        self,
        closes: list[Decimal],
        highs: list[Decimal],
        lows: list[Decimal],
    ) -> RegimeResult:
        """
        Detect market regime based on price data.

        Args:
            closes: List of closing prices (oldest first)
            highs: List of high prices
            lows: List of low prices

        Returns:
            RegimeResult with detected regime and indicators
        """
        reasons = []

        # Calculate EMAs
        ema_20 = calculate_ema(closes, self.ema_short_period)
        ema_50 = calculate_ema(closes, self.ema_medium_period)
        ema_200 = calculate_ema(closes, self.ema_long_period)

        # Calculate ATR and volatility
        atr = calculate_atr(highs, lows, closes, self.atr_period)
        current_price = closes[-1] if closes else None

        atr_percentage = None
        if atr and current_price:
            atr_percentage = calculate_atr_percentage(atr, current_price)

        volatility = calculate_historical_volatility(closes, self.volatility_period)

        # Check for high volatility first (overrides other regimes)
        if volatility is not None:
            vol_regime = calculate_volatility_regime(
                volatility, high_threshold=self.high_volatility_threshold
            )
            if vol_regime == "HIGH":
                reasons.append(f"High volatility: {volatility:.2%}")
                return RegimeResult(
                    regime=MarketRegime.HIGH_VOLATILITY,
                    confidence=Decimal("0.8"),
                    reasons=reasons,
                    ema_20=ema_20,
                    ema_50=ema_50,
                    ema_200=ema_200,
                    atr_percentage=atr_percentage,
                    volatility=volatility,
                )

        # Need at least EMA 200 for trend detection
        if ema_200 is None:
            reasons.append("Insufficient data for EMA 200")
            return RegimeResult(
                regime=MarketRegime.RANGE,
                confidence=Decimal("0.3"),
                reasons=reasons,
                ema_20=ema_20,
                ema_50=ema_50,
                ema_200=ema_200,
                atr_percentage=atr_percentage,
                volatility=volatility,
            )

        # Calculate EMA slope
        ema_200_slope = calculate_ema_slope(
            calculate_ema_series(closes, self.ema_long_period),
            lookback=10,
        )

        # Check for TREND_UP
        # Conditions:
        # - close > EMA200
        # - EMA50 > EMA200
        # - EMA200 slope positive
        if (
            current_price is not None
            and ema_50 is not None
            and current_price > ema_200
            and ema_50 > ema_200
            and ema_200_slope is not None
            and ema_200_slope > self.slope_threshold
        ):
            reasons.append(f"Price {current_price} > EMA200 {ema_200}")
            reasons.append(f"EMA50 {ema_50} > EMA200 {ema_200}")
            reasons.append(f"EMA200 slope {ema_200_slope:.4f} > threshold")

            # Calculate confidence based on distance and slope
            distance = (current_price - ema_200) / ema_200
            confidence = min(Decimal("0.9"), Decimal("0.5") + distance * 10)

            return RegimeResult(
                regime=MarketRegime.TREND_UP,
                confidence=confidence,
                reasons=reasons,
                ema_20=ema_20,
                ema_50=ema_50,
                ema_200=ema_200,
                atr_percentage=atr_percentage,
                volatility=volatility,
            )

        # Check for TREND_DOWN
        # Conditions:
        # - close < EMA200
        # - EMA50 < EMA200
        # - EMA200 slope negative
        if (
            current_price is not None
            and ema_50 is not None
            and current_price < ema_200
            and ema_50 < ema_200
            and ema_200_slope is not None
            and ema_200_slope < -self.slope_threshold
        ):
            reasons.append(f"Price {current_price} < EMA200 {ema_200}")
            reasons.append(f"EMA50 {ema_50} < EMA200 {ema_200}")
            reasons.append(f"EMA200 slope {ema_200_slope:.4f} < threshold")

            # Calculate confidence based on distance and slope
            distance = (ema_200 - current_price) / ema_200
            confidence = min(Decimal("0.9"), Decimal("0.5") + distance * 10)

            return RegimeResult(
                regime=MarketRegime.TREND_DOWN,
                confidence=confidence,
                reasons=reasons,
                ema_20=ema_20,
                ema_50=ema_50,
                ema_200=ema_200,
                atr_percentage=atr_percentage,
                volatility=volatility,
            )

        # Default to RANGE
        reasons.append("No clear trend detected")
        if ema_200_slope is not None:
            reasons.append(f"EMA200 slope {ema_200_slope:.4f} near zero")

        # Check if EMAs are close together (range characteristic)
        if ema_50 is not None:
            ema_distance = abs(ema_50 - ema_200) / ema_200
            if ema_distance < self.range_distance_threshold:
                reasons.append(f"EMAs close together: {ema_distance:.4%}")

        return RegimeResult(
            regime=MarketRegime.RANGE,
            confidence=Decimal("0.6"),
            reasons=reasons,
            ema_20=ema_20,
            ema_50=ema_50,
            ema_200=ema_200,
            atr_percentage=atr_percentage,
            volatility=volatility,
        )


def calculate_ema_series(
    prices: list[Decimal],
    period: int,
) -> list[Optional[Decimal]]:
    """Calculate EMA series (helper function)."""
    from app.indicators.ema import calculate_ema_series as _calculate_ema_series
    return _calculate_ema_series(prices, period)
