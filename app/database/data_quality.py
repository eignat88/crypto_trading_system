from dataclasses import dataclass
from decimal import Decimal
from typing import Optional
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import async_session_factory

logger = structlog.get_logger()


@dataclass
class QualityCheckResult:
    """Result of a quality check."""
    check_name: str
    passed: bool
    total_rows: int
    failed_rows: int
    error_message: Optional[str] = None


@dataclass
class DataQualityReport:
    """Complete data quality report."""
    symbol: str
    interval: str
    total_candles: int
    valid_candles: int
    invalid_candles: int
    checks: list[QualityCheckResult]
    overall_passed: bool


class DataQualityChecker:
    """Checks data quality for candles."""

    async def check_candle_quality(
        self,
        symbol: str,
        interval: str,
    ) -> DataQualityReport:
        """
        Run all quality checks on candles.

        Args:
            symbol: Trading pair symbol
            interval: Time interval

        Returns:
            DataQualityReport with check results
        """
        async with async_session_factory() as session:
            # Get instrument_id
            instrument_id = await self._get_instrument_id(session, symbol)
            if instrument_id is None:
                return DataQualityReport(
                    symbol=symbol,
                    interval=interval,
                    total_candles=0,
                    valid_candles=0,
                    invalid_candles=0,
                    checks=[],
                    overall_passed=False,
                )

            # Get total candles
            total = await self._count_candles(session, instrument_id, interval)

            # Run all checks
            checks = []

            # Check 1: high >= open
            check1 = await self._check_high_gte_open(session, instrument_id, interval)
            checks.append(check1)

            # Check 2: high >= close
            check2 = await self._check_high_gte_close(session, instrument_id, interval)
            checks.append(check2)

            # Check 3: low <= open
            check3 = await self._check_low_lte_open(session, instrument_id, interval)
            checks.append(check3)

            # Check 4: low <= close
            check4 = await self._check_low_lte_close(session, instrument_id, interval)
            checks.append(check4)

            # Check 5: high >= low
            check5 = await self._check_high_gte_low(session, instrument_id, interval)
            checks.append(check5)

            # Check 6: volume >= 0
            check6 = await self._check_volume_gte_zero(session, instrument_id, interval)
            checks.append(check6)

            # Check 7: close > 0
            check7 = await self._check_close_gt_zero(session, instrument_id, interval)
            checks.append(check7)

            # Calculate summary
            invalid_candles = sum(c.failed_rows for c in checks)
            valid_candles = total - invalid_candles
            overall_passed = all(c.passed for c in checks)

            # Mark invalid candles in database
            if invalid_candles > 0:
                await self._mark_invalid_candles(session, instrument_id, interval)

            # Generate report
            report = DataQualityReport(
                symbol=symbol,
                interval=interval,
                total_candles=total,
                valid_candles=valid_candles,
                invalid_candles=invalid_candles,
                checks=checks,
                overall_passed=overall_passed,
            )

            logger.info(
                "quality_check_completed",
                symbol=symbol,
                interval=interval,
                total=total,
                valid=valid_candles,
                invalid=invalid_candles,
                passed=overall_passed,
            )

            return report

    async def _get_instrument_id(
        self, session: AsyncSession, symbol: str
    ) -> Optional[int]:
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

    async def _count_candles(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> int:
        """Count total candles."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        return result.scalar()

    async def _check_high_gte_open(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: high >= open."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND high_price < open_price
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="high_gte_open",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _check_high_gte_close(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: high >= close."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND high_price < close_price
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="high_gte_close",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _check_low_lte_open(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: low <= open."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND low_price > open_price
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="low_lte_open",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _check_low_lte_close(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: low <= close."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND low_price > close_price
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="low_lte_close",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _check_high_gte_low(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: high >= low."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND high_price < low_price
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="high_gte_low",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _check_volume_gte_zero(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: volume >= 0."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND volume < 0
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="volume_gte_zero",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _check_close_gt_zero(
        self, session: AsyncSession, instrument_id: int, interval: str
    ) -> QualityCheckResult:
        """Check: close > 0."""
        result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM dds.candle
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND close_price <= 0
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        failed = result.scalar()
        total = await self._count_candles(session, instrument_id, interval)

        return QualityCheckResult(
            check_name="close_gt_zero",
            passed=failed == 0,
            total_rows=total,
            failed_rows=failed,
        )

    async def _mark_invalid_candles(
        self, session: AsyncSession, instrument_id: int, interval: str
    ):
        """Mark candles that fail quality checks as invalid."""
        await session.execute(
            text(
                """
                UPDATE dds.candle
                SET is_valid = false,
                    validation_errors = jsonb_build_object(
                        'high_gte_open', high_price < open_price,
                        'high_gte_close', high_price < close_price,
                        'low_lte_open', low_price > open_price,
                        'low_lte_close', low_price > close_price,
                        'high_gte_low', high_price < low_price,
                        'volume_gte_zero', volume < 0,
                        'close_gt_zero', close_price <= 0
                    )
                WHERE instrument_id = :instrument_id
                  AND interval_code = :interval
                  AND (
                      high_price < open_price
                      OR high_price < close_price
                      OR low_price > open_price
                      OR low_price > close_price
                      OR high_price < low_price
                      OR volume < 0
                      OR close_price <= 0
                  )
                """
            ),
            {"instrument_id": instrument_id, "interval": interval},
        )
        await session.commit()
