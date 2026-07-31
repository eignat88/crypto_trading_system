from decimal import Decimal


def calculate_average_volume(
    volumes: list[Decimal],
    period: int = 20,
) -> Decimal | None:
    """
    Calculate Average Volume.

    Args:
        volumes: List of volumes (oldest first)
        period: Period for calculation (default: 20)

    Returns:
        Average volume or None if not enough data
    """
    if len(volumes) < period:
        return None

    return sum(volumes[-period:]) / Decimal(period)


def calculate_volume_ratio(
    current_volume: Decimal,
    average_volume: Decimal,
) -> Decimal:
    """
    Calculate Volume Ratio (current / average).

    Args:
        current_volume: Current volume
        average_volume: Average volume

    Returns:
        Volume ratio as decimal (e.g., 1.5 for 150%)
    """
    if average_volume == 0:
        return Decimal(0)
    return current_volume / average_volume


def calculate_volume_trend(
    volumes: list[Decimal],
    short_period: int = 5,
    long_period: int = 20,
) -> str | None:
    """
    Calculate Volume Trend.

    Args:
        volumes: List of volumes (oldest first)
        short_period: Short-term period (default: 5)
        long_period: Long-term period (default: 20)

    Returns:
        'INCREASING', 'DECREASING', or 'STABLE'
    """
    if len(volumes) < long_period:
        return None

    short_avg = sum(volumes[-short_period:]) / Decimal(short_period)
    long_avg = sum(volumes[-long_period:]) / Decimal(long_period)

    if long_avg == 0:
        return "STABLE"

    ratio = short_avg / long_avg

    if ratio > Decimal("1.2"):
        return "INCREASING"
    elif ratio < Decimal("0.8"):
        return "DECREASING"
    else:
        return "STABLE"


def calculate_on_balance_volume(
    closes: list[Decimal],
    volumes: list[Decimal],
) -> list[Decimal] | None:
    """
    Calculate On-Balance Volume (OBV).

    Args:
        closes: List of closing prices (oldest first)
        volumes: List of volumes (oldest first)

    Returns:
        List of OBV values or None if not enough data
    """
    if len(closes) < 2 or len(volumes) < 2:
        return None

    obv_values = [volumes[0]]

    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            # Price up, add volume
            obv_values.append(obv_values[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            # Price down, subtract volume
            obv_values.append(obv_values[-1] - volumes[i])
        else:
            # Price unchanged, no change
            obv_values.append(obv_values[-1])

    return obv_values


def calculate_vwap(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    volumes: list[Decimal],
) -> Decimal | None:
    """
    Calculate Volume Weighted Average Price (VWAP).

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of closing prices
        volumes: List of volumes

    Returns:
        VWAP value or None if not enough data
    """
    if not all([highs, lows, closes, volumes]):
        return None

    if len(highs) != len(lows) or len(highs) != len(closes) or len(highs) != len(volumes):
        return None

    # Calculate typical price for each period
    typical_prices = [
        (highs[i] + lows[i] + closes[i]) / Decimal(3)
        for i in range(len(highs))
    ]

    # Calculate cumulative (typical price * volume)
    cumulative_tpv = Decimal(0)
    cumulative_volume = Decimal(0)

    for tp, vol in zip(typical_prices, volumes):
        cumulative_tpv += tp * vol
        cumulative_volume += vol

    if cumulative_volume == 0:
        return None

    return cumulative_tpv / cumulative_volume
