from decimal import Decimal

import pytest

from app.exchange.fill_simulator import FillResult, FillSimulator
from app.exchange.paper_execution_engine import (
    ExecutionRequest,
    ExecutionStatus,
    OrderSide,
    PaperExecutionEngine,
)


class RecordingFillSimulator(FillSimulator):
    def __init__(self) -> None:
        self.called = False

    def execute(self, quantity: Decimal, market_price: Decimal) -> FillResult:
        self.called = True
        return super().execute(quantity, market_price)


def test_market_buy_fill() -> None:
    engine = PaperExecutionEngine()

    result = engine.execute(
        ExecutionRequest(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("0.1"),
        ),
        Decimal("60000"),
    )

    assert result.status == ExecutionStatus.FILLED
    assert result.quantity == Decimal("0.1")
    assert result.price == Decimal("60000")


def test_market_sell_fill() -> None:
    engine = PaperExecutionEngine()
    engine.execute(
        ExecutionRequest(
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            quantity=Decimal("2"),
        ),
        Decimal("2500"),
    )

    result = engine.execute(
        ExecutionRequest(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("1"),
        ),
        Decimal("3000"),
    )

    assert result.side == OrderSide.SELL
    assert engine.positions["ETHUSDT"].quantity == Decimal("1")
    assert engine.positions["ETHUSDT"].average_price == Decimal("2500")


def test_sell_cannot_exceed_current_position() -> None:
    engine = PaperExecutionEngine()

    with pytest.raises(ValueError, match="exceeds position"):
        engine.execute(
            ExecutionRequest(
                symbol="ETHUSDT",
                side=OrderSide.SELL,
                quantity=Decimal("1"),
            ),
            Decimal("3000"),
        )


def test_invalid_quantity() -> None:
    engine = PaperExecutionEngine()

    with pytest.raises(ValueError):
        engine.execute(
            ExecutionRequest(
                symbol="BTCUSDT",
                side=OrderSide.BUY,
                quantity=Decimal("0"),
            ),
            Decimal("60000"),
        )
