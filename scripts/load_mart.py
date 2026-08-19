"""Restore paper-reporting state from DDS and load analytical MART tables."""

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database.connection import async_session_factory  # noqa: E402
from app.database.repositories.postgres_paper_repository import (  # noqa: E402
    PostgresPaperRepository,
)
from app.etl.mart_etl import MartETL  # noqa: E402
from app.reporting.paper_metrics import PaperMetricsCollector  # noqa: E402
from app.reporting.paper_pnl import PaperPnLTracker  # noqa: E402
from app.reporting.paper_restore import restore_trade_events  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exchange", default="bybit")
    args = parser.parse_args()
    async with async_session_factory() as session:
        repository = PostgresPaperRepository(session)
        tracker = PaperPnLTracker(initial_capital=Decimal("10000"))
        tracker.restore_snapshots(await repository.load_pnl_snapshots())
        collector = PaperMetricsCollector(tracker)
        restore_trade_events(collector, await repository.load_orders(),
                             await repository.load_fills())
        result = await MartETL(session, tracker, collector, args.exchange).load()
    print(f"daily={result.daily}, trades={result.trades}, "
          f"drawdowns={result.drawdowns}, monthly={result.monthly}")


if __name__ == "__main__":
    asyncio.run(main())
