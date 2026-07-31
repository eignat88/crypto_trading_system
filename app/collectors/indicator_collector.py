from decimal import Decimal

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import async_session_factory
from app.indicators.atr import calculate_atr
from app.indicators.ema import calculate_ema
from app.indicators.market_regime import MarketRegimeDetector
from app.indicators.rsi import calculate_rsi
from app.indicators.volatility import calculate_historical_volatility

logger = structlog.get_logger()


class IndicatorCollector:
    """Calculates and stores technical indicators."""

    def __init__(self):
        self.regime_detector = MarketRegimeDetector()

    async def calculate_and_store_indicators(
        self,
        symbol: str,
        interval: str,
    ) -> int:
        """
        Calculate indicators for all candles of a symbol/interval.

        Args:
            symbol: Trading pair symbol
            interval: Time interval

        Returns:
            Number of candles processed
        """
        async with async_session_factory() as session:
            # Get instrument_id
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                logger.warning("instrument_not_found", symbol=symbol)
                return 0

            # Get candles that need indicators
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
            )

            # Extract price data
            closes = [Decimal(str(c["close_price"])) for c in candles]
            highs = [Decimal(str(c["high_price"])) for c in candles]
            lows = [Decimal(str(c["low_price"])) for c in candles]

            # Calculate indicators for each candle
            processed = 0
            for i, candle in enumerate(candles):
                candle_id = candle["candle_id"]

                # Get historical data up to this candle
                historical_closes = closes[: i + 1]
                historical_highs = highs[: i + 1]
                historical_lows = lows[: i + 1]

                # Calculate EMA 20
                ema_20 = calculate_ema(historical_closes, 20)
                if ema_20 is not None:
                    await self._store_indicator(
                        session, candle_id, "EMA", ema_20, {"period": 20}
                    )

                # Calculate EMA 50
                ema_50 = calculate_ema(historical_closes, 50)
                if ema_50 is not None:
                    await self._store_indicator(
                        session, candle_id, "EMA", ema_50, {"period": 50}
                    )

                # Calculate EMA 200
                ema_200 = calculate_ema(historical_closes, 200)
                if ema_200 is not None:
                    await self._store_indicator(
                        session, candle_id, "EMA", ema_200, {"period": 200}
                    )

                # Calculate RSI 14
                rsi = calculate_rsi(historical_closes, 14)
                if rsi is not None:
                    await self._store_indicator(
                        session, candle_id, "RSI", rsi, {"period": 14}
                    )

                # Calculate ATR 14
                atr = calculate_atr(historical_highs, historical_lows, historical_closes, 14)
                if atr is not None:
                    await self._store_indicator(
                        session, candle_id, "ATR", atr, {"period": 14}
                    )

                # Calculate Historical Volatility
                volatility = calculate_historical_volatility(historical_closes, 20)
                if volatility is not None:
                    await self._store_indicator(
                        session, candle_id, "VOLATILITY", volatility, {"period": 20}
                    )

                # Calculate Market Regime
                if len(historical_closes) >= 200:
                    regime_result = self.regime_detector.detect(
                        historical_closes, historical_highs, historical_lows
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
            )

            return processed

    async def _get_instrument_id(
        self, session: AsyncSession, symbol: str
    ) -> int | None:
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
    ) -> list[dict]:
        """Get candles that need indicators calculated."""
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

    async def _store_indicator(
        self,
        session: AsyncSession,
        candle_id: int,
        indicator_name: str,
        value: Decimal,
        params: dict,
    ):
        """Store a calculated indicator."""
        import json

        await session.execute(
            text(
                """
                INSERT INTO dds.indicator (
                    candle_id, indicator_name, indicator_value, indicator_params
                )
                VALUES (:candle_id, :indicator_name, :value, :params)
                ON CONFLICT (candle_id, indicator_name, indicator_params)
                DO UPDATE SET indicator_value = :value, calculated_at = now()
                """
            ),
            {
                "candle_id": candle_id,
                "indicator_name": indicator_name,
                "value": value,
                "params": json.dumps(params),
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
    ):
        """Store market regime."""
        import json

        await session.execute(
            text(
                """
                INSERT INTO dds.market_regime (
                    candle_id, regime, confidence, reasons,
                    ema_20, ema_50, ema_200, atr_percentage, volatility
                ) VALUES (
                    :candle_id, :regime, :confidence, :reasons,
                    :ema_20, :ema_50, :ema_200, :atr_percentage, :volatility
                )
                ON CONFLICT (candle_id)
                DO UPDATE SET
                    regime = :regime,
                    confidence = :confidence,
                    reasons = :reasons,
                    calculated_at = now()
                """
            ),
            {
                "candle_id": candle_id,
                "regime": regime,
                "confidence": confidence,
                "reasons": json.dumps(reasons),
                "ema_20": ema_20,
                "ema_50": ema_50,
                "ema_200": ema_200,
                "atr_percentage": atr_percentage,
                "volatility": volatility,
            },
        )
