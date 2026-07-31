from decimal import Decimal


def calculate_rsi(
    prices: list[Decimal],
    period: int = 14,
) -> Decimal | None:
    """
    Calculate Relative Strength Index (RSI).

    Args:
        prices: List of closing prices (oldest first)
        period: RSI period (default: 14)

    Returns:
        RSI value (0-100) or None if not enough data
    """
    if len(prices) < period + 1:
        return None

    # Calculate price changes
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Separate gains and losses
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [abs(min(change, Decimal(0))) for change in changes]

    # Initial average gain/loss (SMA for first period)
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)

    # Calculate RSI using smoothed averages
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / Decimal(period)

    # Calculate RSI
    if avg_loss == 0:
        return Decimal(100)

    rs = avg_gain / avg_loss
    rsi = Decimal(100) - (Decimal(100) / (Decimal(1) + rs))

    return rsi


def calculate_rsi_series(
    prices: list[Decimal],
    period: int = 14,
) -> list[Decimal | None]:
    """
    Calculate RSI series for all prices.

    Args:
        prices: List of closing prices (oldest first)
        period: RSI period (default: 14)

    Returns:
        List of RSI values (None for insufficient data)
    """
    if len(prices) < period + 1:
        return [None] * len(prices)

    rsi_values: list[Decimal | None] = [None] * period

    # Calculate price changes
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]

    # Separate gains and losses
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [abs(min(change, Decimal(0))) for change in changes]

    # Initial average gain/loss (SMA for first period)
    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)

    # Calculate first RSI
    if avg_loss == 0:
        rsi_values.append(Decimal(100))
    else:
        rs = avg_gain / avg_loss
        rsi = Decimal(100) - (Decimal(100) / (Decimal(1) + rs))
        rsi_values.append(rsi)

    # Calculate subsequent RSIs
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / Decimal(period)

        if avg_loss == 0:
            rsi_values.append(Decimal(100))
        else:
            rs = avg_gain / avg_loss
            rsi = Decimal(100) - (Decimal(100) / (Decimal(1) + rs))
            rsi_values.append(rsi)

    return rsi_values
