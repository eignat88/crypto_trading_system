from decimal import Decimal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.model_versions import INDICATOR_MODEL_VERSION, REGIME_MODEL_VERSION
from app.database.connection import async_session_factory
from app.indicators.atr import calculate_atr
from app.indicators.ema import calculate_ema_series
from app.indicators.market_regime import MarketRegimeDetector
from app.indicators.rsi import calculate_rsi
from app.indicators.volatility import calculate_historical_volatility

logger = structlog.get_logger()


class IndicatorCollector:
    """Calculates and stores versioned technical indicators and market regimes."""

    def __init__(
        self,
        indicator_model_version: str = INDICATOR_MODEL_VERSION,
        regime_model_version: str = REGIME_MODEL_VERSION,
    ):
        if not indicator_model_version:
            raise ValueError("indicator_model_version must be non-empty")
        if not regime_model_version:
            raise ValueError("regime_model_version must be non-empty")
        self.indicator_model_version = indicator_model_version
        self.regime_model_version = regime_model_version
        self.regime_detector = MarketRegimeDetector()

    async def calculate_and_store_indicators(
        self,
        symbol: str,
        interval: str,
    ) -> int:
        """Calculate and store indicators for all valid candles."""
        async with async_session_factory() as session:
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                logger.warning("instrument_not_found", symbol=symbol)
                return 0

            candles = await self._get_candles_for_indicators(
                session, instrument_id, interval
            )
            if not candles:
                logger.info("no_candles_for_indicators", symbol=symbol, interval=interval)
                return 0

            logger.info(
                "calculating_indicators",
                symbol=symbol,
                interval=interval,
                candles=len(candles),
                indicator_model_version=self.indicator_model_version,
                regime_model_version=self.regime_model_version,
            )

            closes = [Decimal(str(c["close_price"])) for c in candles]
            highs = [Decimal(str(c["high_price"])) for c in candles]
            lows = [Decimal(str(c["low_price"])) for c in candles]

            ema_20_series = calculate_ema_series(closes, 20)
            ema_50_series = calculate_ema_series(closes, 50)
            ema_200_series = calculate_ema_series(closes, 200)

            processed = 0
            for i, candle in enumerate(candles):
                candle_id = candle["candle_id"]
                historical_closes = closes[: i + 1]
                historical_highs = highs[: i + 1]
                historical_lows = lows[: i + 1]

                ema_20 = ema_20_series[i]
                if ema_20 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_20, {"period": 20})

                ema_50 = ema_50_series[i]
                if ema_50 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_50, {"period": 50})

                ema_200 = ema_200_series[i]
                if ema_200 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_200, {"period": 200})

                rsi = calculate_rsi(historical_closes, 14)
                if rsi is not None:
                    await self._store_indicator(session, candle_id, "RSI", rsi, {"period": 14})

                atr = calculate_atr(historical_highs, historical_lows, historical_closes, 14)
                if atr is not None:
                    await self._store_indicator(session, candle_id, "ATR", atr, {"period": 14})

                volatility = calculate_historical_volatility(
                    historical_closes,
                    20,
                    timeframe=interval,
                )
                if volatility is not None:
                    await self._store_indicator(
                        session, candle_id, "VOLATILITY", volatility, {"period": 20}
                    )

                if len(historical_closes) >= 200:
                    regime_result = self.regime_detector.detect(
                        historical_closes,
                        historical_highs,
                        historical_lows,
                        timeframe=interval,
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
                if processed % 100 == 0:
                    await session.commit()
                    logger.info("indicators_progress", processed=processed, total=len(candles))

            await session.commit()
            logger.info(
                "indicators_completed",
                symbol=symbol,
                interval=interval,
                processed=processed,
                indicator_model_version=self.indicator_model_version,
                regime_model_version=self.regime_model_version,
            )
            return processed

    async def calculate_missing(
        self,
        symbol: str,
        interval: str,
    ) -> int:
        """Calculate indicators only for candles that don't have them yet.

        This is the incremental calculation method used by MarketPipeline.
        It finds the last calculated indicator and only processes new candles.

        Returns:
            Number of candles processed.
        """
        async with async_session_factory() as session:
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                logger.warning("instrument_not_found", symbol=symbol)
                return 0

            last_indicator_candle_id = await self._get_last_indicator_candle_id(
                session, instrument_id, interval
            )

            # Get candles after the last calculated indicator
            # For warmup, we need 200 candles before the new ones
            candles = await self._get_candles_for_indicators(
                session, instrument_id, interval, after_candle_id=last_indicator_candle_id
            )

            if not candles:
                logger.info("no_new_candles_for_indicators", symbol=symbol, interval=interval)
                return 0

            # For warmup, we need historical candles
            # Get the last 200 candles before the first new candle
            if candles:
                first_new_candle_id = candles[0]["candle_id"]
                warmup_candles = await self._get_warmup_candles(
                    session, instrument_id, interval, first_new_candle_id, warmup_size=200
                )
                # Combine warmup + new candles
                all_candles = warmup_candles + candles
                # Track where new candles start
                warmup_count = len(warmup_candles)
            else:
                all_candles = candles
                warmup_count = 0

            logger.info(
                "calculating_missing_indicators",
                symbol=symbol,
                interval=interval,
                new_candles=len(candles),
                warmup_candles=warmup_count,
                indicator_model_version=self.indicator_model_version,
                regime_model_version=self.regime_model_version,
            )

            closes = [Decimal(str(c["close_price"])) for c in all_candles]
            highs = [Decimal(str(c["high_price"])) for c in all_candles]
            lows = [Decimal(str(c["low_price"])) for c in all_candles]

            ema_20_series = calculate_ema_series(closes, 20)
            ema_50_series = calculate_ema_series(closes, 50)
            ema_200_series = calculate_ema_series(closes, 200)

            processed = 0
            # Only process new candles (skip warmup)
            for i in range(warmup_count, len(all_candles)):
                candle = all_candles[i]
                candle_id = candle["candle_id"]
                historical_closes = closes[: i + 1]
                historical_highs = highs[: i + 1]
                historical_lows = lows[: i + 1]

                ema_20 = ema_20_series[i]
                if ema_20 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_20, {"period": 20})

                ema_50 = ema_50_series[i]
                if ema_50 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_50, {"period": 50})

                ema_200 = ema_200_series[i]
                if ema_200 is not None:
                    await self._store_indicator(session, candle_id, "EMA", ema_200, {"period": 200})

                rsi = calculate_rsi(historical_closes, 14)
                if rsi is not None:
                    await self._store_indicator(session, candle_id, "RSI", rsi, {"period": 14})

                atr = calculate_atr(historical_highs, historical_lows, historical_closes, 14)
                if atr is not None:
                    await self._store_indicator(session, candle_id, "ATR", atr, {"period": 14})

                volatility = calculate_historical_volatility(
                    historical_closes,
                    20,
                    timeframe=interval,
                )
                if volatility is not None:
                    await self._store_indicator(
                        session, candle_id, "VOLATILITY", volatility, {"period": 20}
                    )

                if len(historical_closes) >= 200:
                    regime_result = self.regime_detector.detect(
                        historical_closes,
                        historical_highs,
                        historical_lows,
                        timeframe=interval,
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
                if processed % 100 == 0:
                    await session.commit()
                    logger.info("indicators_progress", processed=processed, total=len(candles))

            await session.commit()
            logger.info(
                "indicators_completed",
                symbol=symbol,
                interval=interval,
                processed=processed,
                indicator_model_version=self.indicator_model_version,
                regime_model_version=self.regime_model_version,
            )
            return processed

    async def _get_warmup_candles(
        self,
        session: AsyncSession,
        instrument_id: int,
        interval: str,
        before_candle_id: int,
        warmup_size: int = 200,
    ) -> list[dict]:
        """Get warmup candles needed for indicator calculation."""
        result = await session.execute(
            text(
                """
                SELECT c.candle_id, c.open_price, c.high_price, c.low_price, c.close_price, c.volume
                FROM dds.candle c
                WHERE c.instrument_id = :instrument_id
                  AND c.interval_code = :interval
                  AND c.is_valid = true
                  AND c.candle_id < :before_candle_id
                ORDER BY c.open_time DESC
                LIMIT :warmup_size
                """
            ),
            {"instrument_id": instrument_id, "interval": interval, "before_candle_id": before_candle_id, "warmup_size": warmup_size},
        )
        candles = [dict(row._mapping) for row in result.fetchall()]
        # Reverse to get chronological order
        candles.reverse()
        return candles

    async def _get_instrument_id(self, session: AsyncSession, symbol: str) -> int | None:
        """Get instrument_id for a symbol."""
        result = await session.execute(
            text(
                """
                SELECT instrument_id
                FROM dds.instrument
                WHERE symbol = :symbol AND exchange_name = 'bybit'
                """
            ),
            {"symbol": symbol},
        )
        row = result.fetchone()
        return row[0] if row else None

    async def _get_candles_for_indicators(
        self,
        session: AsyncSession,
        instrument_id: int,
        interval: str,
        after_candle_id: int | None = None,
    ) -> list[dict]:
        """Get valid candles ordered from oldest to newest.

        Args:
            after_candle_id: If provided, only return candles with id > this value.
                            Used for incremental calculation.
        """
        if after_candle_id is not None:
            result = await session.execute(
                text(
                    """
                    SELECT c.candle_id, c.open_price, c.high_price, c.low_price, c.close_price, c.volume
                    FROM dds.candle c
                    WHERE c.instrument_id = :instrument_id
                      AND c.interval_code = :interval
                      AND c.is_valid = true
                      AND c.candle_id > :after_candle_id
                    ORDER BY c.open_time ASC
                    """
                ),
                {"instrument_id": instrument_id, "interval": interval, "after_candle_id": after_candle_id},
            )
        else:
            result = await session.execute(
                text(
                    """
                    SELECT c.candle_id, c.open_price, c.high_price, c.low_price, c.close_price, c.volume
                    FROM dds.candle c
                    WHERE c.instrument_id = :instrument_id
                      AND c.interval_code = :interval
                      AND c.is_valid = true
                    ORDER BY c.open_time ASC
                    """
                ),
                {"instrument_id": instrument_id, "interval": interval},
            )
        return [dict(row._mapping) for row in result.fetchall()]

    async def _get_last_indicator_candle_id(
        self,
        session: AsyncSession,
        instrument_id: int,
        interval: str,
    ) -> int | None:
        """Get the candle_id of the last calculated indicator."""
        result = await session.execute(
            text(
                """
                SELECT MAX(i.candle_id)
                FROM dds.indicator i
                JOIN dds.candle c ON c.candle_id = i.candle_id
                WHERE c.instrument_id = :instrument_id
                  AND c.interval_code = :interval
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        row = result.fetchone()
        return row[0] if row and row[0] is not None else None

    async def _store_indicator(
        self,
        session: AsyncSession,
        candle_id: int,
        indicator_name: str,
        value: Decimal,
        params: dict,
    ) -> None:
        """Store a calculated indicator idempotently within its model version."""
        import json

        await session.execute(
            text(
                """
                INSERT INTO dds.indicator (
                    candle_id, indicator_name, indicator_value, indicator_params, model_version
                ) VALUES (
                    :candle_id, :indicator_name, :value, CAST(:params AS jsonb), :model_version
                )
                ON CONFLICT (candle_id, indicator_name, indicator_params, model_version)
                DO UPDATE SET
                    indicator_value = EXCLUDED.indicator_value,
                    calculated_at = now()
                """
            ),
            {
                "candle_id": candle_id,
                "indicator_name": indicator_name,
                "value": value,
                "params": json.dumps(params, sort_keys=True, separators=(",", ":")),
                "model_version": self.indicator_model_version,
            },
        )

    async def _store_regime(
        self,
        session: AsyncSession,
        candle_id: int,
        regime: str,
        confidence: Decimal,
        reasons: list[str],
        ema_20: Decimal | None,
        ema_50: Decimal | None,
        ema_200: Decimal | None,
        atr_percentage: Decimal | None,
        volatility: Decimal | None,
    ) -> None:
        """Store market regime idempotently within its regime model version."""
        import json

        await session.execute(
            text(
                """
                INSERT INTO dds.market_regime (
                    candle_id, regime, confidence, reasons,
                    ema_20, ema_50, ema_200, atr_percentage, volatility,
                    indicator_model_version, regime_model_version
                ) VALUES (
                    :candle_id, :regime, :confidence, CAST(:reasons AS jsonb),
                    :ema_20, :ema_50, :ema_200, :atr_percentage, :volatility,
                    :indicator_model_version, :regime_model_version
                )
                ON CONFLICT (candle_id, regime_model_version)
                DO UPDATE SET
                    regime = EXCLUDED.regime,
                    confidence = EXCLUDED.confidence,
                    reasons = EXCLUDED.reasons,
                    ema_20 = EXCLUDED.ema_20,
                    ema_50 = EXCLUDED.ema_50,
                    ema_200 = EXCLUDED.ema_200,
                    atr_percentage = EXCLUDED.atr_percentage,
                    volatility = EXCLUDED.volatility,
                    indicator_model_version = EXCLUDED.indicator_model_version,
                    calculated_at = now()
                """
            ),
            {
                "candle_id": candle_id,
                "regime": regime,
                "confidence": confidence,
                "reasons": json.dumps(reasons, ensure_ascii=False),
                "ema_20": ema_20,
                "ema_50": ema_50,
                "ema_200": ema_200,
                "atr_percentage": atr_percentage,
                "volatility": volatility,
                "indicator_model_version": self.indicator_model_version,
                "regime_model_version": self.regime_model_version,
            },
        )
