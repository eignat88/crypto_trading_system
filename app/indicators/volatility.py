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

    # Calculate log returns
    log_returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_return = float(closes[i] / closes[i - 1])
            log_returns.append(math.log(log_return))

    if len(log_returns) < period:
        return None

    # Calculate standard deviation of log returns
    recent_returns = log_returns[-period:]
    mean_return = sum(recent_returns) / len(recent_returns)
    variance = sum((r - mean_return) ** 2 for r in recent_returns) / (len(recent_returns) - 1)
    std_dev = math.sqrt(variance)

    volatility = Decimal(str(std_dev))

    # Annualize (assuming 365 trading days for crypto)
    if annualize:
        volatility = volatility * Decimal(str(math.sqrt(365)))

    return volatility


def calculate_volatility_regime(
    volatility: Decimal,
    low_threshold: Decimal = Decimal("0.3"),
    high_threshold: Decimal = Decimal("0.8"),
) -> str:
    """
    Determine volatility regime.

    Args:
        volatility: Current volatility
        low_threshold: Low volatility threshold
        high_threshold: High volatility threshold

    Returns:
        'LOW', 'NORMAL', or 'HIGH'
    """
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
    """
    Calculate Bollinger Bands.

    Args:
        closes: List of closing prices (oldest first)
        period: Period for calculation (default: 20)
        std_dev_multiplier: Standard deviation multiplier (default: 2)

    Returns:
        Tuple of (upper_band, middle_band, lower_band) or None
    """
    if len(closes) < period:
        return None

    # Calculate SMA
    sma = sum(closes[-period:]) / Decimal(period)

    # Calculate standard deviation
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / Decimal(period)
    std_dev = Decimal(str(math.sqrt(float(variance))))

    # Calculate bands
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
    """
    Calculate Keltner Channels.

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of closing prices
        ema_period: EMA period (default: 20)
        atr_period: ATR period (default: 10)
        atr_multiplier: ATR multiplier (default: 1.5)

    Returns:
        Tuple of (upper_channel, middle_channel, lower_channel) or None
    """
    if len(closes) < max(ema_period, atr_period):
        return None

    # Calculate EMA (middle channel)
    from app.indicators.ema import calculate_ema
    ema = calculate_ema(closes, ema_period)
    if ema is None:
        return None

    # Calculate ATR
    from app.indicators.atr import calculate_atr
    atr = calculate_atr(highs, lows, closes, atr_period)
    if atr is None:
        return None

    # Calculate channels
    upper_channel = ema + atr * atr_multiplier
    lower_channel = ema - atr * atr_multiplier

    return (upper_channel, ema, lower_channel)
