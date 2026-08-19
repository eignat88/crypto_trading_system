"""Load the current paper reporting state into phase-one MART tables."""

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config.settings import settings  # noqa: E402
from app.database.connection import async_session_factory  # noqa: E402
from app.reporting.mart_etl import MartETL  # noqa: E402
from app.reporting.paper_metrics import PaperMetricsCollector  # noqa: E402
from app.reporting.paper_pnl import PaperPnLTracker  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load paper reporting aggregates into MART")
    parser.add_argument("--exchange", default="bybit")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    tracker = PaperPnLTracker(initial_capital=Decimal(str(settings.paper_initial_balance)))
    collector = PaperMetricsCollector(tracker)
    async with async_session_factory() as session, session.begin():
        result = await MartETL(session, tracker, collector, args.exchange).load()
    print(
        "MART load complete: "
        f"daily={result.daily_performance}, trades={result.trade_statistics}, "
        f"drawdowns={result.drawdown_history}, monthly={result.monthly_returns}"
    )


if __name__ == "__main__":
    asyncio.run(main())
