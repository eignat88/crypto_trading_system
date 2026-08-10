from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.walk_forward import (
    WalkForwardConfig,
    generate_walk_forward_windows,
    run_fixed_parameter_walk_forward,
)


UTC = timezone.utc


def _candle(ts: datetime) -> dict:
    return {
        "symbol": "BTCUSDT",
        "open_time": ts,
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
        "volume": Decimal("1"),
        "indicators": {
            "ema_20": Decimal("100"),
            "ema_50": Decimal("99"),
            "ema_200": Decimal("98"),
            "rsi": Decimal("50"),
            "atr": Decimal("1"),
            "volatility": Decimal("0.1"),
            "regime": "RANGE",
            "regime_confidence": Decimal("0.6"),
        },
    }


def test_generate_180_60_60_windows_for_730_days():
    start = datetime(2024, 8, 10, tzinfo=UTC)
    end = datetime(2026, 8, 10, tzinfo=UTC)
    windows = generate_walk_forward_windows(start, end, WalkForwardConfig())

    assert len(windows) == 9
    assert windows[0].train_start == start
    assert windows[0].train_end == datetime(2025, 2, 6, tzinfo=UTC)
    assert windows[0].test_start == datetime(2025, 2, 6, tzinfo=UTC)
    assert windows[0].test_end == datetime(2025, 4, 7, tzinfo=UTC)
    assert windows[-1].test_end <= end


def test_generate_rejects_range_shorter_than_one_complete_window():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 6, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="too short"):
        generate_walk_forward_windows(start, end, WalkForwardConfig())


def test_fixed_parameter_walk_forward_uses_only_complete_test_window():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    config = WalkForwardConfig(train_days=1, test_days=1, step_days=1)
    end = datetime(2026, 1, 3, tzinfo=UTC)
    candles = [_candle(start + timedelta(hours=hour)) for hour in range(48)]

    result = run_fixed_parameter_walk_forward(
        candles=candles,
        symbol="BTCUSDT",
        interval="1h",
        start=start,
        end=end,
        config=config,
    )

    assert len(result.windows) == 1
    window = result.windows[0]
    assert window.candle_count == 24
    assert window.total_trades == 0
    assert window.total_pnl == Decimal("0")
    assert window.return_pct == Decimal("0")
    assert result.total_oos_pnl == Decimal("0")
    assert result.flat_windows == 1


def test_fixed_parameter_walk_forward_rejects_missing_test_candle():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    config = WalkForwardConfig(train_days=1, test_days=1, step_days=1)
    end = datetime(2026, 1, 3, tzinfo=UTC)
    test_start = datetime(2026, 1, 2, tzinfo=UTC)
    candles = [_candle(test_start + timedelta(hours=hour)) for hour in range(23)]

    with pytest.raises(ValueError, match="Incomplete test window"):
        run_fixed_parameter_walk_forward(
            candles=candles,
            symbol="BTCUSDT",
            interval="1h",
            start=start,
            end=end,
            config=config,
        )
