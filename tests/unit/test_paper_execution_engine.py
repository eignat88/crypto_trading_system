from decimal import Decimal

import pytest

from app.exchange.paper_execution_engine import (
    ExecutionRequest,
    ExecutionStatus,
    OrderSide,
    PaperExecutionEngine,
)


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

    result = engine.execute(
        ExecutionRequest(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            quantity=Decimal("1"),
        ),
        Decimal("3000"),
    )

    assert result.side == OrderSide.SELL


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
