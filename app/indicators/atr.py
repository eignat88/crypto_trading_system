from decimal import Decimal
from typing import Optional


def calculate_true_range(
    high: Decimal,
    low: Decimal,
    previous_close: Decimal,
) -> Decimal:
    """
    Calculate True Range (TR).

    TR = max(high - low, abs(high - previous_close), abs(low - previous_close))
    """
    hl = high - low
    hc = abs(high - previous_close)
    lc = abs(low - previous_close)
    return max(hl, hc, lc)


def calculate_atr(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    period: int = 14,
) -> Optional[Decimal]:
    """
    Calculate Average True Range (ATR).

    Args:
        highs: List of high prices (oldest first)
        lows: List of low prices (oldest first)
        closes: List of closing prices (oldest first)
        period: ATR period (default: 14)

    Returns:
        ATR value or None if not enough data
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    # Calculate True Range for each period
    true_ranges = []
    for i in range(1, len(highs)):
        tr = calculate_true_range(highs[i], lows[i], closes[i - 1])
        true_ranges.append(tr)

    # Initial ATR is SMA of first 'period' True Ranges
    atr = sum(true_ranges[:period]) / Decimal(period)

    # Calculate subsequent ATRs using smoothed average
    for tr in true_ranges[period:]:
        atr = (atr * Decimal(period - 1) + tr) / Decimal(period)

    return atr


def calculate_atr_series(
    highs: list[Decimal],
    lows: list[Decimal],
    closes: list[Decimal],
    period: int = 14,
) -> list[Optional[Decimal]]:
    """
    Calculate ATR series for all prices.

    Args:
        highs: List of high prices (oldest first)
        lows: List of low prices (oldest first)
        closes: List of closing prices (oldest first)
        period: ATR period (default: 14)

    Returns:
        List of ATR values (None for insufficient data)
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return [None] * len(highs)

    atr_values: list[Optional[Decimal]] = [None] * period

    # Calculate True Range for each period
    true_ranges = []
    for i in range(1, len(highs)):
        tr = calculate_true_range(highs[i], lows[i], closes[i - 1])
        true_ranges.append(tr)

    # Initial ATR is SMA of first 'period' True Ranges
    atr = sum(true_ranges[:period]) / Decimal(period)
    atr_values.append(atr)

    # Calculate subsequent ATRs using smoothed average
    for tr in true_ranges[period:]:
        atr = (atr * Decimal(period - 1) + tr) / Decimal(period)
        atr_values.append(atr)

    return atr_values


def calculate_atr_percentage(
    atr: Decimal,
    price: Decimal,
) -> Decimal:
    """
    Calculate ATR as percentage of price.

    Args:
        atr: ATR value
        price: Current price

    Returns:
        ATR percentage (e.g., 0.02 for 2%)
    """
    if price == 0:
        return Decimal(0)
    return atr / price
