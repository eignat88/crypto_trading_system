from decimal import Decimal

import pytest

from app.models.paper_state import PaperRuntimeState


class InMemoryPaperStateRepository:
    def __init__(self) -> None:
        self.state = None
        self.positions = []

    async def save_state(self, state: PaperRuntimeState) -> None:
        self.state = state

    async def load_state(self) -> PaperRuntimeState | None:
        return self.state

    async def save_position(self, position) -> None:
        self.positions.append(position)

    async def load_positions(self):
        return self.positions


@pytest.mark.asyncio
async def test_runtime_state_can_be_restored_after_restart() -> None:
    repository = InMemoryPaperStateRepository()

    await repository.save_state(
        PaperRuntimeState(
            last_market_sequence=5,
            cash_balance=Decimal("1000"),
        )
    )

    restored = await repository.load_state()

    assert restored is not None
    assert restored.last_market_sequence == 5
    assert restored.cash_balance == Decimal("1000")


@pytest.mark.asyncio
async def test_position_is_restored_after_engine_restart() -> None:
    from app.models.paper_position_state import PaperPositionState

    repository = InMemoryPaperStateRepository()

    position = PaperPositionState(
        symbol="BTCUSDT",
        quantity=Decimal("0.01"),
        average_price=Decimal("60000"),
    )

    await repository.save_position(position)

    restarted_positions = await repository.load_positions()

    assert restarted_positions[0].symbol == "BTCUSDT"
    assert restarted_positions[0].quantity == Decimal("0.01")
    assert restarted_positions[0].average_price == Decimal("60000")
