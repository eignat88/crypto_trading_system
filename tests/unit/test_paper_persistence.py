from decimal import Decimal

from app.exchange.paper_repository import PaperStateSerializer
from app.exchange.paper_state import PaperState


def test_paper_state_roundtrip():
    state = PaperState(
        balances={"USDT": Decimal("1000")},
        positions={"BTCUSDT": Decimal("0.1")},
    )

    restored = PaperStateSerializer.loads(
        PaperStateSerializer.dumps(state)
    )

    assert restored.balances["USDT"] == "1000"
    assert restored.positions["BTCUSDT"] == "0.1"
