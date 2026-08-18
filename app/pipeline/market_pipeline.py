"""Market pipeline that orchestrates candle loading and indicator calculation."""

import structlog

from app.collectors.indicator_collector import IndicatorCollector

logger = structlog.get_logger()


class MarketPipeline:
    """Orchestrates the flow: RAW -> DDS candles -> DDS indicators.

    This pipeline connects the candle loading step with indicator calculation,
    ensuring indicators are calculated incrementally for new candles only.
    """

    def __init__(
        self,
        indicator_collector: IndicatorCollector,
    ):
        self.indicator_collector = indicator_collector

    async def process_new_candles(
        self,
        symbol: str,
        interval: str,
    ) -> int:
        """Process new candles by calculating missing indicators.

        This method should be called after DDS candle loading is complete.
        It calculates indicators only for candles that don't have them yet.

        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            interval: Candle interval (e.g., "1h")

        Returns:
            Number of candles processed.
        """
        logger.info(
            "pipeline_processing",
            symbol=symbol,
            interval=interval,
        )

        processed = await self.indicator_collector.calculate_missing(
            symbol=symbol,
            interval=interval,
        )

        logger.info(
            "pipeline_completed",
            symbol=symbol,
            interval=interval,
            processed=processed,
        )

        return processed
