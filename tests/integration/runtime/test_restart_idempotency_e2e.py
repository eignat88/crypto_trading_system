from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.models.candle import Candle
from app.models.market_event import MarketEvent
from tests.helpers.runtime.paper_runtime_factory import make_runtime
from tests.helpers.runtime.runtime_fixture import MemoryCheckpointRepository
from tests.helpers.runtime.state_assertions import action_counts, assert_btc_position


def market_event(sequence: int = 1) -> MarketEvent:
    opened = datetime(2026, 8, 20, 10, tzinfo=UTC) + timedelta(minutes=sequence - 1)
    return MarketEvent(
        Candle(
            "BTCUSDT", opened, opened + timedelta(minutes=1),
            *(Decimal("60000"),) * 4, Decimal("1"),
        ),
        sequence,
    )


@pytest.mark.asyncio
async def test_restart_replay_creates_no_duplicate_actions() -> None:
    repository = MemoryCheckpointRepository()
    first, first_engine, strategy, risk = make_runtime(repository, [market_event()])
    await first.run_async()
    await first_engine.flush()
    assert (strategy.signals, risk.decisions) == (1, 1)
    assert action_counts(repository) == (1, 1, 1)
    assert_btc_position(first_engine)

    second, second_engine, strategy2, risk2 = make_runtime(repository, [market_event()])
    await second.run_async()
    assert (strategy2.signals, risk2.decisions) == (0, 0)
    assert action_counts(repository) == (1, 1, 1)
    assert_btc_position(second_engine)
