import asyncio
import sys

import structlog

from app.config.settings import settings
from app.database.connection import check_database_connection

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.stdlib._NAME_TO_LEVEL[settings.log_level.lower()]
    ),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def main():
    """Main entry point."""
    logger.info("starting_system", mode=settings.trading_mode.value)

    # Check database connection
    db_ok = await check_database_connection()
    if not db_ok:
        logger.critical("database_connection_failed")
        sys.exit(1)

    logger.info("database_connected")

    # TODO: Add more initialization logic here

    logger.info("system_ready")


if __name__ == "__main__":
    asyncio.run(main())
