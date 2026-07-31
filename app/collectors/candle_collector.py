import asyncio
import json
from datetime import datetime, timedelta

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import async_session_factory
from app.exchange.base_exchange import BaseExchange, Candle
from app.exchange.intervals import interval_duration

logger = structlog.get_logger()


def align_to_interval(value: datetime, duration: timedelta) -> datetime:
    """Floor a timestamp to an exchange candle boundary."""
    duration_seconds = int(duration.total_seconds())
    aligned_seconds = int(value.timestamp()) // duration_seconds * duration_seconds
    return datetime.fromtimestamp(aligned_seconds, tz=value.tzinfo)


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
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")
        total_loaded = 0
        duration = interval_duration(interval)
        current_start = align_to_interval(start_date, duration)
        page_size = min(batch_size, 1000)

        logger.info(
            "loading_started",
            symbol=symbol,
            interval=interval,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
        )

        while current_start < end_date:
            # Bybit orders klines newest-first. A bounded inclusive window ensures
            # that a full response cannot omit candles at the start of the page.
            batch_end = min(
                end_date,
                current_start + duration * (page_size - 1),
            )
            # Load batch
            candles = await self.exchange.get_candles(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=batch_end,
                limit=page_size,
            )

            if not candles:
                raise ValueError(
                    f"Empty candle batch for expected range {current_start.isoformat()} "
                    f"to {batch_end.isoformat()}"
                )

            candles.sort(key=lambda candle: candle.open_time)
            self._validate_batch(candles, duration, current_start)
            max_open_time = max(candle.open_time for candle in candles)

            # Store candles
            async with async_session_factory() as session:
                async with session.begin():
                    loaded_count = await self._store_candles(session, candles)
                    await self._store_api_response(session, candles)
                    await self._update_checkpoint(
                        session, symbol, interval, current_start, max_open_time, loaded_count
                    )
                total_loaded += loaded_count

            logger.info(
                "batch_loaded",
                symbol=symbol,
                interval=interval,
                batch_size=len(candles),
                loaded=loaded_count,
                total=total_loaded,
                current_time=max_open_time.isoformat(),
            )

            # Move to next batch (start after last candle)
            current_start = max_open_time + duration

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
                        "source_payload": (
                            json.dumps(candle.source_payload)
                            if candle.source_payload is not None
                            else None
                        ),
                    },
                )
                if result.rowcount > 0:
                    inserted += 1
            except Exception:
                logger.exception(
                    "candle_store_error",
                    symbol=candle.symbol,
                    open_time=candle.open_time.isoformat(),
                )
                raise
        return inserted

    @staticmethod
    def _validate_batch(
        candles: list[Candle], duration: timedelta, expected_start: datetime
    ) -> None:
        times = [candle.open_time for candle in candles]
        if len(times) != len(set(times)):
            raise ValueError("Duplicate candle open_time in Bybit response")
        if any(later <= earlier for earlier, later in zip(times, times[1:])):
            raise ValueError("Candle open_time is not strictly monotonic")
        expected_pairs = zip(times, times[1:])
        if any(later - earlier != duration for earlier, later in expected_pairs):
            raise ValueError("Gap detected in Bybit candle response")
        if times[0] != expected_start:
            raise ValueError(
                f"Batch starts at {times[0].isoformat()}, expected {expected_start.isoformat()}"
            )

    async def _store_api_response(self, session: AsyncSession, candles: list[Candle]) -> None:
        response_payload = getattr(candles, "response_payload", None)
        if response_payload is None:
            return
        await session.execute(
            text(
                """
                INSERT INTO raw_system.api_responses (
                    exchange_name, endpoint, request_id, request_time,
                    response_time, status_code, request_payload, response_payload
                ) VALUES ('bybit', '/v5/market/kline', :request_id, :request_time,
                          now(), 200, :request_payload, :response_payload)
                """
            ),
            {
                "request_id": getattr(candles, "request_id", None),
                "request_time": getattr(candles, "request_time", None),
                "request_payload": json.dumps(getattr(candles, "request_payload", None)),
                "response_payload": json.dumps(response_payload),
            },
        )

    async def _update_checkpoint(
        self,
        session: AsyncSession,
        symbol: str,
        interval: str,
        start_time: datetime,
        end_time: datetime,
        rows_loaded: int,
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
                    :start_time, :end_time, :rows_loaded, 'success', now()
                )
                """
            ),
            {
                "exchange_name": "bybit",
                "symbol": symbol,
                "interval_code": interval,
                "start_time": start_time,
                "end_time": end_time,
                "rows_loaded": rows_loaded,
            },
        )

    async def get_last_checkpoint(self, symbol: str, interval: str) -> datetime | None:
        """Get last successful checkpoint for resume."""
        async with async_session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT max(end_time)
                    FROM raw_system.loading_journal
                    WHERE exchange_name = 'bybit'
                      AND symbol = :symbol
                      AND interval_code = :interval
                      AND status = 'success'
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
        error_message: str | None = None,
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
