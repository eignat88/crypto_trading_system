"""Tests for indicator pipeline integration."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.collectors.indicator_collector import IndicatorCollector
from app.pipeline.market_pipeline import MarketPipeline


class TestMarketPipeline:
    """Tests for MarketPipeline class."""

    def test_pipeline_initialization(self) -> None:
        """Test pipeline initializes with indicator collector."""
        collector = MagicMock(spec=IndicatorCollector)
        pipeline = MarketPipeline(indicator_collector=collector)
        assert pipeline.indicator_collector is collector

    @pytest.mark.asyncio
    async def test_process_new_candles_calls_collector(self) -> None:
        """Test process_new_candles calls indicator collector."""
        collector = MagicMock(spec=IndicatorCollector)
        collector.calculate_missing = AsyncMock(return_value=10)

        pipeline = MarketPipeline(indicator_collector=collector)

        processed = await pipeline.process_new_candles(
            symbol="BTCUSDT",
            interval="1h",
        )

        assert processed == 10
        collector.calculate_missing.assert_called_once_with(
            symbol="BTCUSDT",
            interval="1h",
        )

    @pytest.mark.asyncio
    async def test_process_new_candles_returns_zero_when_no_new(self) -> None:
        """Test process_new_candles returns 0 when no new candles."""
        collector = MagicMock(spec=IndicatorCollector)
        collector.calculate_missing = AsyncMock(return_value=0)

        pipeline = MarketPipeline(indicator_collector=collector)

        processed = await pipeline.process_new_candles(
            symbol="ETHUSDT",
            interval="5m",
        )

        assert processed == 0


class TestIndicatorCollectorIncremental:
    """Tests for IndicatorCollector incremental calculation."""

    @pytest.mark.asyncio
    async def test_calculate_missing_returns_zero_when_no_instrument(self) -> None:
        """Test calculate_missing returns 0 when instrument not found."""
        collector = IndicatorCollector()

        with patch.object(collector, "_get_instrument_id", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            result = await collector.calculate_missing("UNKNOWN", "1h")
            assert result == 0

    @pytest.mark.asyncio
    async def test_calculate_missing_returns_zero_when_no_new_candles(self) -> None:
        """Test calculate_missing returns 0 when no new candles."""
        collector = IndicatorCollector()

        with (
            patch.object(collector, "_get_instrument_id", new_callable=AsyncMock) as mock_get_id,
            patch.object(collector, "_get_last_indicator_candle_id", new_callable=AsyncMock) as mock_last,
            patch.object(collector, "_get_candles_for_indicators", new_callable=AsyncMock) as mock_candles,
        ):
            mock_get_id.return_value = 1
            mock_last.return_value = 1000
            mock_candles.return_value = []

            result = await collector.calculate_missing("BTCUSDT", "1h")
            assert result == 0

    @pytest.mark.asyncio
    async def test_get_last_indicator_candle_id_returns_none_when_empty(self) -> None:
        """Test _get_last_indicator_candle_id returns None when no indicators."""
        collector = IndicatorCollector()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [None]
        mock_session.execute.return_value = mock_result

        result = await collector._get_last_indicator_candle_id(mock_session, 1, "1h")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_indicator_candle_id_returns_max_id(self) -> None:
        """Test _get_last_indicator_candle_id returns max candle_id."""
        collector = IndicatorCollector()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = [42]
        mock_session.execute.return_value = mock_result

        result = await collector._get_last_indicator_candle_id(mock_session, 1, "1h")
        assert result == 42

    @pytest.mark.asyncio
    async def test_get_warmup_candles_returns_reversed_order(self) -> None:
        """Test _get_warmup_candles returns candles in chronological order."""
        collector = IndicatorCollector()

        mock_session = AsyncMock()
        mock_result = MagicMock()
        # Simulate DESC order result (newest first)
        mock_result.fetchall.return_value = [
            MagicMock(_mapping={"candle_id": 3, "open_price": 100, "high_price": 110, "low_price": 90, "close_price": 105, "volume": 1000}),
            MagicMock(_mapping={"candle_id": 2, "open_price": 95, "high_price": 105, "low_price": 85, "close_price": 100, "volume": 900}),
            MagicMock(_mapping={"candle_id": 1, "open_price": 90, "high_price": 100, "low_price": 80, "close_price": 95, "volume": 800}),
        ]
        mock_session.execute.return_value = mock_result

        result = await collector._get_warmup_candles(mock_session, 1, "1h", 4, warmup_size=3)

        # Should be reversed to chronological order
        assert result[0]["candle_id"] == 1
        assert result[1]["candle_id"] == 2
        assert result[2]["candle_id"] == 3
