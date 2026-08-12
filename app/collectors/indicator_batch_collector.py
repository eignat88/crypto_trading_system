from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

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
        """Recalculate and persist derived rows for every valid candle."""
        async with async_session_factory() as session:
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                logger.warning("instrument_not_found", symbol=symbol)
                return 0

            candles = await self._get_candles_for_indicators(session, instrument_id, interval)
            if not candles:
                logger.info("no_candles_for_indicators", symbol=symbol, interval=interval)
                return 0

            series = _calculate_series(candles, interval)
            logger.info(
                "batch_indicators_started",
                symbol=symbol,
                interval=interval,
                candles=len(candles),
            )

            processed = 0
            for i, candle in enumerate(candles):
                await self._store_derived_at(session, candle, i, series)
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

    async def calculate_and_store_missing_indicators(
        self,
        symbol: str,
        interval: str,
        *,
        start_time: datetime,
        end_time: datetime,
    ) -> int:
        """Persist only missing current-version derived rows in a target window.

        The indicator series is calculated over the complete valid candle history so
        recursive EMA/Wilder calculations remain bit-for-bit compatible with the
        full batch implementation. Only target candles whose current model-version
        indicator/regime coverage is incomplete are written to PostgreSQL.
        """
        if start_time.tzinfo is None or end_time.tzinfo is None:
            raise ValueError("incremental derived timestamps must be timezone-aware")
        if end_time <= start_time:
            return 0

        async with async_session_factory() as session:
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                logger.warning("instrument_not_found", symbol=symbol)
                return 0

            target_ids = await self._get_missing_derived_candle_ids(
                session,
                instrument_id,
                interval,
                start_time=start_time,
                end_time=end_time,
            )
            if not target_ids:
                logger.info(
                    "incremental_indicators_up_to_date",
                    symbol=symbol,
                    interval=interval,
                    start=start_time.isoformat(),
                    end=end_time.isoformat(),
                )
                return 0

            candles = await self._get_candles_for_indicators(session, instrument_id, interval)
            if not candles:
                raise RuntimeError(f"No valid DDS candles for {symbol} {interval}")

            indices = _target_indices(candles, target_ids)
            found_ids = {int(candles[index]["candle_id"]) for index in indices}
            missing_from_history = target_ids - found_ids
            if missing_from_history:
                raise RuntimeError(
                    f"Target DDS candles disappeared while deriving {symbol}: "
                    f"{sorted(missing_from_history)}"
                )

            series = _calculate_series(candles, interval)
            logger.info(
                "incremental_indicators_started",
                symbol=symbol,
                interval=interval,
                target_candles=len(indices),
                history_candles=len(candles),
                indicator_model_version=self.indicator_model_version,
                regime_model_version=self.regime_model_version,
            )

            for index in indices:
                await self._store_derived_at(session, candles[index], index, series)

            await session.commit()
            logger.info(
                "incremental_indicators_completed",
                symbol=symbol,
                interval=interval,
                processed=len(indices),
            )
            return len(indices)

    async def _get_missing_derived_candle_ids(
        self,
        session: AsyncSession,
        instrument_id: int,
        interval: str,
        *,
        start_time: datetime,
        end_time: datetime,
    ) -> set[int]:
        result = await session.execute(
            text(
                """
                SELECT c.candle_id
                FROM dds.candle c
                WHERE c.instrument_id = :instrument_id
                  AND c.interval_code = :interval
                  AND c.is_valid = true
                  AND c.open_time >= :start_time
                  AND c.open_time < :end_time
                  AND (
                    NOT EXISTS (
                      SELECT 1 FROM dds.indicator x
                      WHERE x.candle_id = c.candle_id
                        AND x.model_version = :indicator_model_version
                        AND x.indicator_name = 'EMA'
                        AND x.indicator_params = '{"period": 20}'::jsonb
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM dds.indicator x
                      WHERE x.candle_id = c.candle_id
                        AND x.model_version = :indicator_model_version
                        AND x.indicator_name = 'EMA'
                        AND x.indicator_params = '{"period": 50}'::jsonb
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM dds.indicator x
                      WHERE x.candle_id = c.candle_id
                        AND x.model_version = :indicator_model_version
                        AND x.indicator_name = 'EMA'
                        AND x.indicator_params = '{"period": 200}'::jsonb
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM dds.indicator x
                      WHERE x.candle_id = c.candle_id
                        AND x.model_version = :indicator_model_version
                        AND x.indicator_name = 'RSI'
                        AND x.indicator_params = '{"period": 14}'::jsonb
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM dds.indicator x
                      WHERE x.candle_id = c.candle_id
                        AND x.model_version = :indicator_model_version
                        AND x.indicator_name = 'ATR'
                        AND x.indicator_params = '{"period": 14}'::jsonb
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM dds.indicator x
                      WHERE x.candle_id = c.candle_id
                        AND x.model_version = :indicator_model_version
                        AND x.indicator_name = 'VOLATILITY'
                        AND x.indicator_params = '{"period": 20}'::jsonb
                    )
                    OR NOT EXISTS (
                      SELECT 1 FROM dds.market_regime mr
                      WHERE mr.candle_id = c.candle_id
                        AND mr.indicator_model_version = :indicator_model_version
                        AND mr.regime_model_version = :regime_model_version
                    )
                  )
                ORDER BY c.open_time
                """
            ),
            {
                "instrument_id": instrument_id,
                "interval": interval,
                "start_time": start_time,
                "end_time": end_time,
                "indicator_model_version": self.indicator_model_version,
                "regime_model_version": self.regime_model_version,
            },
        )
        return {int(row[0]) for row in result.fetchall()}

    async def _store_derived_at(
        self,
        session: AsyncSession,
        candle: dict,
        index: int,
        series: tuple[
            list[Decimal | None],
            list[Decimal | None],
            list[Decimal | None],
            list[Decimal | None],
            list[Decimal | None],
            list[Decimal | None],
            list[Decimal],
        ],
    ) -> None:
        (
            ema_20_series,
            ema_50_series,
            ema_200_series,
            rsi_14_series,
            atr_14_series,
            volatility_20_series,
            closes,
        ) = series
        candle_id = int(candle["candle_id"])
        ema_20 = ema_20_series[index]
        ema_50 = ema_50_series[index]
        ema_200 = ema_200_series[index]
        rsi = rsi_14_series[index]
        atr = atr_14_series[index]
        volatility = volatility_20_series[index]

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

        if index >= 199:
            slope = _ema_slope_at(ema_200_series, index, lookback=10)
            atr_percentage = (
                calculate_atr_percentage(atr, closes[index])
                if atr is not None and closes[index]
                else None
            )
            regime_result = classify_regime(
                detector=self.regime_detector,
                current_price=closes[index],
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


def _calculate_series(
    candles: list[dict],
    interval: str,
) -> tuple[
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal | None],
    list[Decimal],
]:
    closes = [Decimal(str(c["close_price"])) for c in candles]
    highs = [Decimal(str(c["high_price"])) for c in candles]
    lows = [Decimal(str(c["low_price"])) for c in candles]
    return (
        calculate_ema_series(closes, 20),
        calculate_ema_series(closes, 50),
        calculate_ema_series(closes, 200),
        calculate_rsi_series(closes, 14),
        calculate_atr_series(highs, lows, closes, 14),
        calculate_historical_volatility_series(closes, 20, timeframe=interval),
        closes,
    )


def _target_indices(candles: list[dict], target_ids: set[int]) -> list[int]:
    return [
        index
        for index, candle in enumerate(candles)
        if int(candle["candle_id"]) in target_ids
    ]


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
