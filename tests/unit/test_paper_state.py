from datetime import datetime
from decimal import Decimal

import pytest

from app.models.paper_state import PaperRuntimeState


def test_runtime_state_validation() -> None:
    state = PaperRuntimeState(
        last_processed_timestamp=datetime(2026, 1, 1),
        last_market_sequence=1,
        cash_balance=Decimal("1000"),
    )

    state.validate()


def test_negative_sequence_is_rejected() -> None:
    state = PaperRuntimeState(last_market_sequence=-1)

    with pytest.raises(ValueError):
        state.validate()
