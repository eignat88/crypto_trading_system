from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine, BacktestResult
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy


_INTERVAL_SECONDS = {
    "5m": 5 * 60,
    "15m": 15 * 60,
    "1h": 60 * 60,
    "4h": 4 * 60 * 60,
    "1d": 24 * 60 * 60,
}


@dataclass(frozen=True)
class WalkForwardConfig:
    train_days: int = 180
    test_days: int = 60
    step_days: int = 60
    initial_balance: Decimal = Decimal("500")
    random_seed: int = 42

    def __post_init__(self) -> None:
        if self.train_days <= 0:
            raise ValueError("train_days must be > 0")
        if self.test_days <= 0:
            raise ValueError("test_days must be > 0")
        if self.step_days <= 0:
            raise ValueError("step_days must be > 0")
        if self.initial_balance <= 0:
            raise ValueError("initial_balance must be > 0")


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


@dataclass(frozen=True)
class WalkForwardWindowResult:
    window: WalkForwardWindow
    candle_count: int
    initial_balance: Decimal
    final_equity: Decimal
    total_pnl: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal

    @property
    def return_pct(self) -> Decimal:
        return self.total_pnl / self.initial_balance


@dataclass(frozen=True)
class WalkForwardResult:
    symbol: str
    interval: str
    config: WalkForwardConfig
    windows: tuple[WalkForwardWindowResult, ...]
    total_oos_pnl: Decimal
    profitable_windows: int
    losing_windows: int
    flat_windows: int
    total_oos_trades: int

    @property
    def profitable_window_rate(self) -> Decimal:
        total = len(self.windows)
        return Decimal(self.profitable_windows) / Decimal(total) if total else Decimal("0")


def generate_walk_forward_windows(
    start: datetime,
    end: datetime,
    config: WalkForwardConfig,
) -> tuple[WalkForwardWindow, ...]:
    """Generate anchored train/test windows without partial final tests."""
    if end <= start:
        raise ValueError("end must be greater than start")

    train_delta = timedelta(days=config.train_days)
    test_delta = timedelta(days=config.test_days)
    step_delta = timedelta(days=config.step_days)

    windows: list[WalkForwardWindow] = []
    anchor = start
    index = 1

    while True:
        train_start = anchor
        train_end = train_start + train_delta
        test_start = train_end
        test_end = test_start + test_delta
        if test_end > end:
            break

        windows.append(
            WalkForwardWindow(
                index=index,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        anchor += step_delta
        index += 1

    if not windows:
        raise ValueError(
            "Requested range is too short for one complete train/test walk-forward window"
        )

    return tuple(windows)


def _validate_test_candles(
    candles: list[dict[str, Any]],
    interval: str,
    window: WalkForwardWindow,
) -> None:
    if interval not in _INTERVAL_SECONDS:
        raise ValueError(f"Unsupported interval: {interval}")

    step = _INTERVAL_SECONDS[interval]
    expected = int((window.test_end - window.test_start).total_seconds() / step)
    if len(candles) != expected:
        raise ValueError(
            f"Incomplete test window {window.index}: expected={expected} actual={len(candles)}"
        )

    for previous, current in zip(candles, candles[1:]):
        delta = (current["open_time"] - previous["open_time"]).total_seconds()
        if delta != step:
            raise ValueError(
                f"Time gap in test window {window.index}: "
                f"{previous['open_time']} -> {current['open_time']}"
            )


def _run_test_window(
    candles: list[dict[str, Any]],
    symbol: str,
    config: WalkForwardConfig,
) -> BacktestResult:
    strategy = TrendDCAStrategy(symbols=[symbol], config=DCAConfig())
    engine = BacktestEngine(
        config=BacktestConfig(
            initial_balance=config.initial_balance,
            random_seed=config.random_seed,
        )
    )
    return engine.run(
        candles=candles,
        strategy=strategy,
        indicator_provider=lambda candle, index: candle["indicators"],
    )


def run_fixed_parameter_walk_forward(
    *,
    candles: list[dict[str, Any]],
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    config: WalkForwardConfig | None = None,
) -> WalkForwardResult:
    """Run fixed TrendDCA parameters on sequential out-of-sample test windows.

    The train slice is deliberately not optimized in this baseline version. It
    defines chronology and future optimization boundaries only. Every test window
    starts from a fresh portfolio, strategy instance, Risk Engine, and deterministic
    slippage RNG with the same seed.
    """
    wf_config = config or WalkForwardConfig()
    windows = generate_walk_forward_windows(start, end, wf_config)

    results: list[WalkForwardWindowResult] = []
    for window in windows:
        test_candles = [
            candle
            for candle in candles
            if window.test_start <= candle["open_time"] < window.test_end
        ]
        _validate_test_candles(test_candles, interval, window)

        result = _run_test_window(test_candles, symbol, wf_config)
        results.append(
            WalkForwardWindowResult(
                window=window,
                candle_count=len(test_candles),
                initial_balance=wf_config.initial_balance,
                final_equity=result.portfolio.total_equity,
                total_pnl=result.total_pnl,
                total_trades=result.total_trades,
                winning_trades=result.winning_trades,
                losing_trades=result.losing_trades,
                win_rate=result.win_rate,
                profit_factor=result.profit_factor,
                max_drawdown=result.max_drawdown,
            )
        )

    total_oos_pnl = sum((item.total_pnl for item in results), Decimal("0"))
    profitable = sum(1 for item in results if item.total_pnl > 0)
    losing = sum(1 for item in results if item.total_pnl < 0)
    flat = len(results) - profitable - losing

    return WalkForwardResult(
        symbol=symbol,
        interval=interval,
        config=wf_config,
        windows=tuple(results),
        total_oos_pnl=total_oos_pnl,
        profitable_windows=profitable,
        losing_windows=losing,
        flat_windows=flat,
        total_oos_trades=sum(item.total_trades for item in results),
    )
