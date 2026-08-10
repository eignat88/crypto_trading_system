import math
from decimal import Decimal


def calculate_historical_volatility(
    closes: list[Decimal],
    period: int = 20,
    annualize: bool = True,
) -> Decimal | None:
    """
    Calculate Historical Volatility.

    Args:
        closes: List of closing prices (oldest first)
        period: Period for calculation (default: 20)
        annualize: If True, annualize the volatility

    Returns:
        Historical volatility as decimal (e.g., 0.5 for 50%) or None
    """
    if len(closes) < period + 1:
        return None

    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_return = float(closes[i] / closes[i - 1])
            log_returns.append(math.log(log_return))

    if len(log_returns) < period:
        return None

    recent_returns = log_returns[-period:]
    first_return = recent_returns[0]
    if all(
        math.isclose(value, first_return, rel_tol=0.0, abs_tol=1e-15)
        for value in recent_returns[1:]
    ):
        return Decimal("0")

    mean_return = sum(recent_returns) / len(recent_returns)
    variance = sum((r - mean_return) ** 2 for r in recent_returns) / (len(recent_returns) - 1)
    std_dev = math.sqrt(variance)

    volatility = Decimal(str(std_dev))
    if annualize:
        volatility = volatility * Decimal(str(math.sqrt(365)))

    return volatility


def calculate_historical_volatility_series(
    closes: list[Decimal],
    period: int = 20,
    annualize: bool = True,
) -> list[Decimal | None]:
    """Calculate the causal historical-volatility value for every candle.

    Each output at index ``i`` is equivalent to calling
    ``calculate_historical_volatility(closes[: i + 1], period, annualize)`` but
    only the rolling ``period`` log returns are processed for that candle.
    """
    values: list[Decimal | None] = [None] * len(closes)
    if len(closes) < period + 1:
        return values

    log_returns: list[float | None] = [None]
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(float(closes[i] / closes[i - 1])))
        else:
            log_returns.append(None)

    annualization_factor = Decimal(str(math.sqrt(365))) if annualize else Decimal(1)

    for i in range(period, len(closes)):
        window = log_returns[i - period + 1 : i + 1]
        if any(value is None for value in window):
            continue

        recent_returns = [float(value) for value in window if value is not None]
        first_return = recent_returns[0]
        if all(
            math.isclose(value, first_return, rel_tol=0.0, abs_tol=1e-15)
            for value in recent_returns[1:]
        ):
            values[i] = Decimal("0")
            continue

        mean_return = sum(recent_returns) / len(recent_returns)
        variance = sum((r - mean_return) ** 2 for r in recent_returns) / (
            len(recent_returns) - 1
        )
        std_dev = Decimal(str(math.sqrt(variance)))
        values[i] = std_dev * annualization_factor

    return values


def calculate_volatility_regime(
    volatility: Decimal,
    low_threshold: Decimal = Decimal("0.3"),
    high_threshold: Decimal = Decimal("0.8"),
) -> str:
    """Determine volatility regime."""
    if volatility < low_threshold:
        return "LOW"
    elif volatility > high_threshold:
        return "HIGH"
    else:
        return "NORMAL"


def calculate_bollinger_bands(
    closes: list[Decimal],
    period: int = 20,
    std_dev_multiplier: Decimal = Decimal("2"),
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Calculate Bollinger Bands."""
    if len(closes) < period:
        return None

    sma = sum(closes[-period:]) / Decimal(period)
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / Decimal(period)
    std_dev = Decimal(str(math.sqrt(float(variance))))

    upper_band = sma + std_dev * std_dev_multiplier
    lower_band = sma - std_dev * std_dev_multiplier

    return (upper_band, sma, lower_band)


def calculate_keltner_channels(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    ema_period: int = 20,
    atr_period: int = 10,
    atr_multiplier: Decimal = Decimal("1.5"),
) -> tuple[Decimal, Decimal, Decimal] | None:
    """Calculate Keltner Channels."""
    if len(closes) < max(ema_period, atr_period):
        return None

    from app.indicators.ema import calculate_ema

    ema = calculate_ema(closes, ema_period)
    if ema is None:
        return None

    from app.indicators.atr import calculate_atr

    atr = calculate_atr(highs, lows, closes, atr_period)
    if atr is None:
        return None

    upper_channel = ema + atr * atr_multiplier
    lower_channel = ema - atr * atr_multiplier

    return (upper_channel, ema, lower_channel)
