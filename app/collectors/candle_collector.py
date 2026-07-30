import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.exchange.base_exchange import BaseExchange, Candle
from app.database.connection import async_session_factory

logger = structlog.get_logger()


class CandleCollector:
    """Collects and stores historical candle data."""

    def __init__(self, exchange: BaseExchange):
        self.exchange = exchange

    async def load_historical_candles(
        self,
        symbol: str,
        interval: str,
        start_date: datetime,
        end_date: datetime,
        batch_size: int = 1000,
    ) -> int:
        """Load historical candles with checkpoint support."""
        total_loaded = 0
        current_start = start_date

        logger.info(
            "loading_started",
            symbol=symbol,
            interval=interval,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

        while current_start < end_date:
            # Load batch
            candles = await self.exchange.get_candles(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_date,
                limit=batch_size,
            )

            if not candles:
                break

            # Store candles
            async with async_session_factory() as session:
                loaded_count = await self._store_candles(session, candles)
                total_loaded += loaded_count

                # Update checkpoint
                last_candle_time = max(c.open_time for c in candles)
                await self._update_checkpoint(
                    session, symbol, interval, current_start, last_candle_time
                )

            logger.info(
                "batch_loaded",
                symbol=symbol,
                interval=interval,
                batch_size=len(candles),
                loaded=loaded_count,
                total=total_loaded,
                current_time=candles[-1].open_time.isoformat(),
            )

            # Move to next batch (start after last candle)
            current_start = candles[-1].open_time + timedelta(seconds=1)

            # Rate limiting
            await asyncio.sleep(0.1)

        logger.info(
            "loading_completed",
            symbol=symbol,
            interval=interval,
            total_loaded=total_loaded,
        )

        return total_loaded

    async def _store_candles(self, session: AsyncSession, candles: list[Candle]) -> int:
        """Store candles in database with duplicate protection."""
        inserted = 0

        for candle in candles:
            try:
                result = await session.execute(
                    text(
                        """
                        INSERT INTO raw_market.candles (
                            exchange_name, symbol, interval_code, open_time,
                            close_time, open_price, high_price, low_price,
                            close_price, volume, quote_volume, trade_count,
                            source_payload
                        ) VALUES (
                            :exchange_name, :symbol, :interval_code, :open_time,
                            :close_time, :open_price, :high_price, :low_price,
                            :close_price, :volume, :quote_volume, :trade_count,
                            :source_payload
                        )
                        ON CONFLICT (exchange_name, symbol, interval_code, open_time)
                        DO NOTHING
                        """
                    ),
                    {
                        "exchange_name": candle.exchange_name,
                        "symbol": candle.symbol,
                        "interval_code": candle.interval_code,
                        "open_time": candle.open_time,
                        "close_time": candle.close_time,
                        "open_price": candle.open_price,
                        "high_price": candle.high_price,
                        "low_price": candle.low_price,
                        "close_price": candle.close_price,
                        "volume": candle.volume,
                        "quote_volume": candle.quote_volume,
                        "trade_count": candle.trade_count,
                        "source_payload": None,
                    },
                )
                if result.rowcount > 0:
                    inserted += 1
            except Exception as e:
                logger.warning(
                    "candle_store_error",
                    symbol=candle.symbol,
                    open_time=candle.open_time.isoformat(),
                    error=str(e),
                )

        await session.commit()
        return inserted

    async def _update_checkpoint(
        self,
        session: AsyncSession,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
    ):
        """Update loading journal checkpoint."""
        await session.execute(
            text(
                """
                INSERT INTO raw_system.loading_journal (
                    exchange_name, symbol, interval_code,
                    start_time, end_time, rows_loaded, status, completed_at
                ) VALUES (
                    :exchange_name, :symbol, :interval_code,
                    :start_time, :end_time, 0, 'in_progress', now()
                )
                """
            ),
            {
                "exchange_name": "bybit",
                "symbol": symbol,
                "interval_code": interval,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        await session.commit()

    async def get_last_checkpoint(
        self, symbol: str, interval: str
    ) -> Optional[datetime]:
        """Get last successful checkpoint for resume."""
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT end_time
                    FROM raw_system.loading_journal
                    WHERE exchange_name = 'bybit'
                      AND symbol = :symbol
                      AND interval_code = :interval
                      AND status = 'success'
                    ORDER BY completed_at DESC
                    LIMIT 1
                    """
                ),
                {"symbol": symbol, "interval": interval},
            )
            row = result.fetchone()
            return row[0] if row else None

    async def update_checkpoint_status(
        self,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        rows_loaded: int,
        status: str = "success",
        error_message: Optional[str] = None,
    ):
        """Update checkpoint status."""
        async with async_session_factory() as session:
            await session.execute(
                text(
                    """
                    UPDATE raw_system.loading_journal
                    SET rows_loaded = :rows_loaded,
                        status = :status,
                        error_message = :error_message,
                        completed_at = now()
                    WHERE exchange_name = 'bybit'
                      AND symbol = :symbol
                      AND interval_code = :interval
                      AND start_time = :start_time
                      AND end_time = :end_time
                    """
                ),
                {
                    "symbol": symbol,
                    "interval": interval,
                    "start_time": start_time,
                    "end_time": end_time,
                    "rows_loaded": rows_loaded,
                    "status": status,
                    "error_message": error_message,
                },
            )
            await session.commit()
