from decimal import Decimal


def assert_btc_position(engine, quantity: str = "0.1", average_price: str = "60000") -> None:
    position = engine.positions["BTCUSDT"]
    assert position.quantity == Decimal(quantity)
    assert position.average_price == Decimal(average_price)


def action_counts(repository) -> tuple[int, int, int]:
    return len(repository.orders), len(repository.fills), len(repository.positions)
