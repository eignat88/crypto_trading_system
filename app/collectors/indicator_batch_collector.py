from decimal import Decimal

import structlog

from app.collectors.indicator_collector import IndicatorCollector
from app.database.connection import async_session_factory
from app.indicators.atr import calculate_atr_percentage, calculate_atr_series
from app.indicators.ema import calculate_ema_series
from app.indicators.market_regime import MarketRegime, RegimeResult
from app.indicators.rsi import calculate_rsi_series
from app.indicators.volatility import (
    calculate_historical_volatility_series,
    calculate_volatility_regime,
)

logger = structlog.get_logger()


class BatchIndicatorCollector(IndicatorCollector):
    """Linear-time batch calculator for long historical candle ranges."""

    async def calculate_and_store_indicators(self, symbol: str, interval: str) -> int:
        async with async_session_factory() as session:
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                logger.warning("instrument_not_found", symbol=symbol)
                return 0

            candles = await self._get_candles_for_indicators(session, instrument_id, interval)
            if not candles:
                logger.info("no_candles_for_indicators", symbol=symbol, interval=interval)
                return 0

            closes = [Decimal(str(c["close_price"])) for c in candles]
            highs = [Decimal(str(c["high_price"])) for c in candles]
            lows = [Decimal(str(c["low_price"])) for c in candles]

            ema_20_series = calculate_ema_series(closes, 20)
            ema_50_series = calculate_ema_series(closes, 50)
            ema_200_series = calculate_ema_series(closes, 200)
            rsi_14_series = calculate_rsi_series(closes, 14)
            atr_14_series = calculate_atr_series(highs, lows, closes, 14)
            volatility_20_series = calculate_historical_volatility_series(
                closes,
                20,
                timeframe=interval,
            )

            logger.info(
                "batch_indicators_started",
                symbol=symbol,
                interval=interval,
                candles=len(candles),
            )

            processed = 0
            for i, candle in enumerate(candles):
                candle_id = candle["candle_id"]
                ema_20 = ema_20_series[i]
                ema_50 = ema_50_series[i]
                ema_200 = ema_200_series[i]
                rsi = rsi_14_series[i]
                atr = atr_14_series[i]
                volatility = volatility_20_series[i]

                if ema_20 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_20, {"period": 20})
                if ema_50 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_50, {"period": 50})
                if ema_200 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_200, {"period": 200})
                if rsi is not None:
                    await self._store_indicator(session, candle_id, "RSI", rsi, {"period": 14})
                if atr is not None:
                    await self._store_indicator(session, candle_id, "ATR", atr, {"period": 14})
                if volatility is not None:
                    await self._store_indicator(
                        session, candle_id, "VOLATILITY", volatility, {"period": 20}
                    )

                if i >= 199:
                    slope = _ema_slope_at(ema_200_series, i, lookback=10)
                    atr_percentage = (
                        calculate_atr_percentage(atr, closes[i]) if atr and closes[i] else None
                    )
                    regime_result = classify_regime(
                        detector=self.regime_detector,
                        current_price=closes[i],
                        ema_20=ema_20,
                        ema_50=ema_50,
                        ema_200=ema_200,
                        ema_200_slope=slope,
                        atr_percentage=atr_percentage,
                        volatility=volatility,
                    )
                    await self._store_regime(
                        session,
                        candle_id,
                        regime_result.regime.value,
                        regime_result.confidence,
                        regime_result.reasons,
                        regime_result.ema_20,
                        regime_result.ema_50,
                        regime_result.ema_200,
                        regime_result.atr_percentage,
                        regime_result.volatility,
                    )

                processed += 1
                if processed % 500 == 0:
                    await session.commit()
                    logger.info(
                        "batch_indicators_progress",
                        symbol=symbol,
                        processed=processed,
                        total=len(candles),
                    )

            await session.commit()
            logger.info(
                "batch_indicators_completed",
                symbol=symbol,
                interval=interval,
                processed=processed,
            )
            return processed


def _ema_slope_at(
    ema_values: list[Decimal | None], index: int, lookback: int = 10
) -> Decimal | None:
    if lookback <= 0:
        raise ValueError("lookback must be positive")
    current = ema_values[index]
    past_index = index - lookback + 1
    if current is None or past_index < 0:
        return None
    past = ema_values[past_index]
    if past is None or past == 0:
        return None
    return (current - past) / past


def classify_regime(
    *,
    detector,
    current_price: Decimal | None,
    ema_20: Decimal | None,
    ema_50: Decimal | None,
    ema_200: Decimal | None,
    ema_200_slope: Decimal | None,
    atr_percentage: Decimal | None,
    volatility: Decimal | None,
) -> RegimeResult:
    """Apply the same classification rules as MarketRegimeDetector.detect()."""
    reasons: list[str] = []

    if volatility is not None:
        vol_regime = calculate_volatility_regime(
            volatility, high_threshold=detector.high_volatility_threshold
        )
        if vol_regime == "HIGH":
            reasons.append(f"High volatility: {volatility:.2%}")
            return RegimeResult(
                MarketRegime.HIGH_VOLATILITY,
                Decimal("0.8"),
                reasons,
                ema_20,
                ema_50,
                ema_200,
                atr_percentage,
                volatility,
            )

    if ema_200 is None:
        reasons.append("Insufficient data for EMA 200")
        return RegimeResult(
            MarketRegime.UNKNOWN,
            Decimal("0"),
            reasons,
            ema_20,
            ema_50,
            ema_200,
            atr_percentage,
            volatility,
        )

    if ema_200_slope is None:
        reasons.append("Insufficient EMA 200 history for slope")
        return RegimeResult(
            MarketRegime.UNKNOWN,
            Decimal("0"),
            reasons,
            ema_20,
            ema_50,
            ema_200,
            atr_percentage,
            volatility,
        )

    if (
        current_price is not None
        and ema_50 is not None
        and current_price > ema_200
        and ema_50 > ema_200
        and ema_200_slope > detector.slope_threshold
    ):
        reasons.append(f"Price {current_price} > EMA200 {ema_200}")
        reasons.append(f"EMA50 {ema_50} > EMA200 {ema_200}")
        reasons.append(f"EMA200 slope {ema_200_slope:.4f} > threshold")
        distance = (current_price - ema_200) / ema_200
        confidence = min(Decimal("0.9"), Decimal("0.5") + distance * 10)
        return RegimeResult(
            MarketRegime.TREND_UP,
            confidence,
            reasons,
            ema_20,
            ema_50,
            ema_200,
            atr_percentage,
            volatility,
        )

    if (
        current_price is not None
        and ema_50 is not None
        and current_price < ema_200
        and ema_50 < ema_200
        and ema_200_slope < -detector.slope_threshold
    ):
        reasons.append(f"Price {current_price} < EMA200 {ema_200}")
        reasons.append(f"EMA50 {ema_50} < EMA200 {ema_200}")
        reasons.append(f"EMA200 slope {ema_200_slope:.4f} < threshold")
        distance = (ema_200 - current_price) / ema_200
        confidence = min(Decimal("0.9"), Decimal("0.5") + distance * 10)
        return RegimeResult(
            MarketRegime.TREND_DOWN,
            confidence,
            reasons,
            ema_20,
            ema_50,
            ema_200,
            atr_percentage,
            volatility,
        )

    reasons.append("No clear trend detected")
    reasons.append(f"EMA200 slope {ema_200_slope:.4f} near zero")
    if ema_50 is not None:
        ema_distance = abs(ema_50 - ema_200) / ema_200
        if ema_distance < detector.range_distance_threshold:
            reasons.append(f"EMAs close together: {ema_distance:.4%}")

    return RegimeResult(
        MarketRegime.RANGE,
        Decimal("0.6"),
        reasons,
        ema_20,
        ema_50,
        ema_200,
        atr_percentage,
        volatility,
    )
