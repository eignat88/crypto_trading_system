from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import asyncpg  # type: ignore[import-untyped]
import structlog

from app.collectors.candle_collector import CandleCollector, align_to_interval
from app.models.candle import Candle
from app.models.market_event import MarketEvent

logger = structlog.get_logger()


class BybitPaperMarketData:
    """Long-running, DDS-backed source of closed Bybit candles.

    Ingestion is deliberately delegated to ``CandleCollector`` and the existing
    PostgreSQL ETL.  This class only coordinates readiness and emits normalized
    events into the existing paper runtime.
    """

    def __init__(
        self,
        *,
        connection: asyncpg.Connection,
        collector: CandleCollector,
        symbols: list[str],
        interval: str,
        warmup_candles: int,
        backfill_buffer: int,
        poll_seconds: float,
        stale_grace_seconds: int,
    ) -> None:
        self.connection = connection
        self.collector = collector
        self.symbols = symbols
        self.interval = interval
        self.warmup_candles = warmup_candles
        self.backfill_buffer = backfill_buffer
        self.poll_seconds = poll_seconds
        self.stale_grace = timedelta(seconds=stale_grace_seconds)
        self.duration = timedelta(hours=1)
        self.ready = False
        self._stopped = asyncio.Event()
        self._last_emitted: dict[str, datetime] = {}

    def stop(self) -> None:
        self._stopped.set()

    def restore_boundary(self, sequence: int, timestamp: datetime | None) -> None:
        """Restore per-symbol emission boundaries from durable runtime state."""
        if timestamp is None or sequence <= 0:
            return
        for index, symbol in enumerate(self.symbols):
            symbol_sequence = int(timestamp.timestamp()) * 10 + index
            self._last_emitted[symbol] = (
                timestamp if symbol_sequence <= sequence else timestamp - self.duration
            )

    @staticmethod
    def _latest_closed_boundary(now: datetime) -> datetime:
        return align_to_interval(now, timedelta(hours=1))

    async def _stats(self) -> dict[str, asyncpg.Record]:
        rows = await self.connection.fetch(
            """SELECT i.symbol, count(*) AS candle_count,
                      min(c.open_time) AS first_candle,
                      max(c.open_time) AS last_candle,
                      max(c.close_time) AS last_close,
                      count(*) - count(DISTINCT c.open_time) AS duplicate_count,
                      count(*) FILTER (WHERE previous_open IS NOT NULL
                         AND c.open_time - previous_open <> interval '1 hour') AS gap_count
               FROM (SELECT c.*, lag(c.open_time) OVER
                       (PARTITION BY c.instrument_id ORDER BY c.open_time) AS previous_open
                     FROM dds.candle c
                     WHERE c.interval_code = $1 AND c.is_valid = true
                       AND c.close_time <= now()) c
               JOIN dds.instrument i ON i.instrument_id = c.instrument_id
               WHERE i.exchange_name = 'bybit' AND i.symbol = ANY($2::text[])
               GROUP BY i.symbol""",
            self.interval,
            self.symbols,
        )
        return {str(row["symbol"]): row for row in rows}

    async def _ingest(self, symbol: str, start: datetime, end: datetime) -> None:
        if start >= end:
            return
        await self.collector.load_historical_candles(symbol, self.interval, start, end)
        await self.connection.fetch(
            "SELECT * FROM dds.load_raw_candles($1, $2, $3, $4)",
            "bybit",
            symbol,
            self.interval,
            end,
        )
        logger.info("market_data_etl_completed", symbol=symbol, interval=self.interval)

    async def bootstrap(self) -> dict[str, int]:
        logger.info("market_data_bootstrap_started", symbols=self.symbols, interval=self.interval)
        self.ready = False
        boundary = self._latest_closed_boundary(datetime.now(UTC))
        stats = await self._stats()
        target = self.warmup_candles + self.backfill_buffer
        for symbol in self.symbols:
            row = stats.get(symbol)
            available = int(row["candle_count"]) if row else 0
            if available < self.warmup_candles:
                start = boundary - self.duration * target
                logger.info(
                    "market_data_backfill_started",
                    symbol=symbol,
                    interval=self.interval,
                    available=available,
                    required=self.warmup_candles,
                    start=start,
                    end=boundary,
                )
                await self._ingest(symbol, start, boundary)
                logger.info("market_data_backfill_completed", symbol=symbol)

        stats = await self._stats()
        # Recover both internal and trailing gaps using explicit timestamp ranges.
        for symbol, row in list(stats.items()):
            if int(row["gap_count"]):
                logger.warning(
                    "market_data_gap_detected", symbol=symbol, gaps=int(row["gap_count"])
                )
                await self._ingest(symbol, row["first_candle"], boundary)
                logger.info("market_data_gap_recovered", symbol=symbol)
            elif row["last_close"] < boundary:
                await self._ingest(symbol, row["last_close"], boundary)

        stats = await self._stats()
        counts = {symbol: int(row["candle_count"]) for symbol, row in stats.items()}
        # On the first process start DDS history is warmup, not a stream backlog.
        # A restored durable boundary takes precedence because the mapping is
        # already populated by ``restore_boundary`` before bootstrap.
        if not self._last_emitted:
            self._last_emitted = {
                symbol: row["last_candle"] for symbol, row in stats.items()
            }
        self.ready = all(
            symbol in stats
            and counts[symbol] >= self.warmup_candles
            and int(stats[symbol]["gap_count"]) == 0
            and int(stats[symbol]["duplicate_count"]) == 0
            and stats[symbol]["last_close"] + self.stale_grace >= boundary
            for symbol in self.symbols
        )
        for symbol in self.symbols:
            event = (
                "market_data_warmup_ready"
                if counts.get(symbol, 0) >= self.warmup_candles
                else "market_data_warmup_insufficient"
            )
            logger.info(
                event, symbol=symbol, candles=counts.get(symbol, 0), required=self.warmup_candles
            )
        logger.info("paper_market_data_ready", ready=self.ready)
        return counts

    async def _new_candles(self) -> list[asyncpg.Record]:
        return list(
            await self.connection.fetch(
                """SELECT i.symbol, c.open_time, c.close_time, c.open_price,
                      c.high_price, c.low_price, c.close_price, c.volume
               FROM dds.candle c JOIN dds.instrument i USING (instrument_id)
               WHERE i.exchange_name='bybit' AND i.symbol=ANY($1::text[])
                 AND c.interval_code=$2 AND c.is_valid=true AND c.close_time <= now()
                 AND c.open_time > COALESCE($3::timestamptz, '-infinity')
               ORDER BY c.open_time, i.symbol""",
                self.symbols,
                self.interval,
                min(self._last_emitted.values()) if self._last_emitted else None,
            )
        )

    async def stream_async(self) -> AsyncIterator[MarketEvent]:
        while not self._stopped.is_set():
            try:
                logger.info("market_data_poll_started")
                await self.bootstrap()
                if not self.ready:
                    logger.warning("market_data_stale")
                else:
                    emitted = 0
                    for row in await self._new_candles():
                        symbol, opened = str(row["symbol"]), row["open_time"]
                        if opened <= self._last_emitted.get(
                            symbol, datetime.min.replace(tzinfo=UTC)
                        ):
                            continue
                        self._last_emitted[symbol] = opened
                        candle = Candle(
                            symbol,
                            opened,
                            row["close_time"],
                            Decimal(row["open_price"]),
                            Decimal(row["high_price"]),
                            Decimal(row["low_price"]),
                            Decimal(row["close_price"]),
                            Decimal(row["volume"]),
                        )
                        sequence = int(opened.timestamp()) * 10 + self.symbols.index(symbol)
                        emitted += 1
                        logger.info("market_data_new_candle", symbol=symbol, open_time=opened)
                        yield MarketEvent(candle=candle, sequence=sequence, source="bybit-rest-dds")
                    if not emitted:
                        logger.info("market_data_no_change")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ready = False
                logger.exception("market_data_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass
