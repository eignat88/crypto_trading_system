from decimal import Decimal


def _rsi_from_averages(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
    """Convert Wilder average gain/loss values to RSI."""
    if avg_gain == 0 and avg_loss == 0:
        return Decimal("50")
    if avg_loss == 0:
        return Decimal("100")

    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def calculate_rsi(
    prices: list[Decimal],
    period: int = 14,
) -> Decimal | None:
    """Calculate RSI using Wilder smoothing."""
    if len(prices) < period + 1:
        return None

    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [abs(min(change, Decimal(0))) for change in changes]

    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / Decimal(period)

    return _rsi_from_averages(avg_gain, avg_loss)


def calculate_rsi_series(
    prices: list[Decimal],
    period: int = 14,
) -> list[Decimal | None]:
    """Calculate the causal RSI series using Wilder smoothing."""
    if len(prices) < period + 1:
        return [None] * len(prices)

    rsi_values: list[Decimal | None] = [None] * period

    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [abs(min(change, Decimal(0))) for change in changes]

    avg_gain = sum(gains[:period]) / Decimal(period)
    avg_loss = sum(losses[:period]) / Decimal(period)
    rsi_values.append(_rsi_from_averages(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / Decimal(period)
        rsi_values.append(_rsi_from_averages(avg_gain, avg_loss))

    return rsi_values
