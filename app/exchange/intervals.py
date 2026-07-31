from datetime import timedelta

INTERVAL_DURATIONS = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}


def interval_duration(interval: str) -> timedelta:
    """Return the exact duration of a supported exchange candle interval."""
    try:
        return INTERVAL_DURATIONS[interval]
    except KeyError as exc:
        raise ValueError(f"Unsupported candle interval: {interval}") from exc
