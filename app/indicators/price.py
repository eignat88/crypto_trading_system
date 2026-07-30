from decimal import Decimal
from typing import Optional


def calculate_price_change(
    current_price: Decimal,
    previous_price: Decimal,
) -> Decimal:
    """
    Calculate price change as percentage.

    Args:
        current_price: Current price
        previous_price: Previous price

    Returns:
        Price change as decimal (e.g., 0.05 for 5%)
    """
    if previous_price == 0:
        return Decimal(0)
    return (current_price - previous_price) / previous_price


def calculate_price_change_series(
    closes: list[Decimal],
    period: int = 1,
) -> list[Optional[Decimal]]:
    """
    Calculate price change series.

    Args:
        closes: List of closing prices (oldest first)
        period: Period for comparison (default: 1)

    Returns:
        List of price changes (None for insufficient data)
    """
    if len(closes) < period + 1:
        return [None] * len(closes)

    changes: list[Optional[Decimal]] = [None] * period

    for i in range(period, len(closes)):
        if closes[i - period] > 0:
            change = (closes[i] - closes[i - period]) / closes[i - period]
            changes.append(change)
        else:
            changes.append(None)

    return changes


def calculate_distance_to_ema(
    price: Decimal,
    ema: Decimal,
) -> Decimal:
    """
    Calculate distance from price to EMA as percentage.

    Args:
        price: Current price
        ema: EMA value

    Returns:
        Distance as decimal (e.g., 0.02 for 2% above EMA)
    """
    if ema == 0:
        return Decimal(0)
    return (price - ema) / ema


def calculate_high_low_range(
    high: Decimal,
    low: Decimal,
) -> Decimal:
    """
    Calculate high-low range as percentage.

    Args:
        high: High price
        low: Low price

    Returns:
        Range as decimal (e.g., 0.03 for 3% range)
    """
    if low == 0:
        return Decimal(0)
    return (high - low) / low


def calculate_max_period(
    prices: list[Decimal],
    period: int,
) -> Optional[Decimal]:
    """
    Calculate maximum price in period.

    Args:
        prices: List of prices (oldest first)
        period: Period for calculation

    Returns:
        Maximum price or None if not enough data
    """
    if len(prices) < period:
        return None

    return max(prices[-period:])


def calculate_min_period(
    prices: list[Decimal],
    period: int,
) -> Optional[Decimal]:
    """
    Calculate minimum price in period.

    Args:
        prices: List of prices (oldest first)
        period: Period for calculation

    Returns:
        Minimum price or None if not enough data
    """
    if len(prices) < period:
        return None

    return min(prices[-period:])
