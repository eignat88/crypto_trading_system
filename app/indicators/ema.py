from decimal import Decimal


def calculate_ema(
    prices: list[Decimal],
    period: int,
    previous_ema: Decimal | None = None,
) -> Decimal | None:
    """
    Calculate Exponential Moving Average (EMA).

    Args:
        prices: List of closing prices (oldest first)
        period: EMA period (e.g., 20, 50, 200)
        previous_ema: Previous EMA value for incremental calculation

    Returns:
        EMA value or None if not enough data
    """
    if len(prices) < period:
        return None

    # Multiplier: 2 / (period + 1)
    multiplier = Decimal(2) / Decimal(period + 1)

    if previous_ema is None:
        # Initial EMA is SMA
        sma = sum(prices[:period]) / Decimal(period)
        return sma
    else:
        # Incremental EMA
        current_price = prices[-1]
        return (current_price - previous_ema) * multiplier + previous_ema


def calculate_ema_series(
    prices: list[Decimal],
    period: int,
) -> list[Decimal | None]:
    """
    Calculate EMA series for all prices.

    Args:
        prices: List of closing prices (oldest first)
        period: EMA period

    Returns:
        List of EMA values (None for insufficient data)
    """
    if len(prices) < period:
        return [None] * len(prices)

    ema_values: list[Decimal | None] = [None] * (period - 1)

    # Calculate initial SMA
    sma = sum(prices[:period]) / Decimal(period)
    ema_values.append(sma)

    # Calculate subsequent EMAs
    current_ema = sma
    multiplier = Decimal(2) / Decimal(period + 1)

    for price in prices[period:]:
        current_ema = (price - current_ema) * multiplier + current_ema
        ema_values.append(current_ema)

    return ema_values


def calculate_ema_slope(
    ema_values: list[Decimal | None],
    lookback: int = 5,
) -> Decimal | None:
    """
    Calculate EMA slope (rate of change).

    Args:
        ema_values: List of EMA values
        lookback: Number of periods to look back for slope

    Returns:
        Slope as decimal or None
    """
    # Filter out None values from the end
    valid_values = [v for v in ema_values if v is not None]

    if len(valid_values) < lookback:
        return None

    # Simple slope: (current - past) / past
    current = valid_values[-1]
    past = valid_values[-lookback]

    if past == 0:
        return None

    return (current - past) / past
