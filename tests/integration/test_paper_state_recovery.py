from decimal import Decimal

import pytest

from app.models.paper_state import PaperRuntimeState


class InMemoryPaperStateRepository:
    def __init__(self) -> None:
        self.state = None

    async def save_state(self, state: PaperRuntimeState) -> None:
        self.state = state

    async def load_state(self) -> PaperRuntimeState | None:
        return self.state


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
