from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.backtest.walk_forward import (
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindow,
    WalkForwardWindowResult,
    generate_walk_forward_windows,
)
from app.indicators.market_regime import MarketRegime
from app.strategies.trend_dca_ema200_slope_p75 import TrendDCAEMA200SlopeP75Strategy


@dataclass(frozen=True)
class WindowThreshold:
    window_index: int
    train_opportunities: int
    threshold: Decimal


@dataclass(frozen=True)
class EMA200SlopeP75WalkForwardResult:
    result: WalkForwardResult
    thresholds: tuple[WindowThreshold, ...]


def _percentile(values: list[Decimal], q: Decimal) -> Decimal:
    if not values:
        raise ValueError("Cannot calculate percentile from empty values")
    if q < 0 or q > 1:
        raise ValueError("Percentile q must be between 0 and 1")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def add_ema200_slope_10(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add causal EMA200 10-value slope to candle indicator dictionaries.

    This uses the current EMA200 and the EMA200 value nine candles earlier,
    matching calculate_ema_slope(..., lookback=10). Only past/current data is
    used for each candle.
    """
    result: list[dict[str, Any]] = []
    for index, candle in enumerate(candles):
        copied = dict(candle)
        indicators = dict(candle["indicators"])
        slope: Decimal | None = None
        if index >= 9:
            current_raw = indicators.get("ema_200")
            past_raw = candles[index - 9]["indicators"].get("ema_200")
            if current_raw is not None and past_raw is not None:
                current = Decimal(str(current_raw))
                past = Decimal(str(past_raw))
                if past != 0:
                    slope = (current - past) / past
        indicators["ema200_slope_10"] = slope
        copied["indicators"] = indicators
        result.append(copied)
    return result


def _is_baseline_entry_opportunity(candle: dict[str, Any]) -> bool:
    indicators = candle["indicators"]
    required = (
        indicators.get("ema_200"),
        indicators.get("ema_50"),
        indicators.get("rsi"),
        indicators.get("regime"),
        indicators.get("ema200_slope_10"),
    )
    if any(value is None for value in required):
        return False

    close = Decimal(str(candle["close"]))
    ema200 = Decimal(str(indicators["ema_200"]))
    ema50 = Decimal(str(indicators["ema_50"]))
    rsi = Decimal(str(indicators["rsi"]))
    volatility_raw = indicators.get("volatility")

    if indicators["regime"] != MarketRegime.TREND_UP:
        return False
    if close <= ema200 or ema50 <= ema200 or rsi > Decimal("45"):
        return False
    if volatility_raw is not None and Decimal(str(volatility_raw)) > Decimal("0.8"):
        return False
    return True


def derive_train_p75_threshold(
    candles: list[dict[str, Any]],
    window: WalkForwardWindow,
) -> tuple[Decimal, int]:
    opportunities = [
        candle
        for candle in candles
        if window.train_start <= candle["open_time"] < window.train_end
        and _is_baseline_entry_opportunity(candle)
    ]
    slopes = [
        Decimal(str(candle["indicators"]["ema200_slope_10"]))
        for candle in opportunities
    ]
    if not slopes:
        raise ValueError(
            f"Window {window.index} has no baseline entry opportunities in TRAIN"
        )
    return _percentile(slopes, Decimal("0.75")), len(slopes)


def _validate_test_window(
    test_candles: list[dict[str, Any]], window: WalkForwardWindow, interval: str
) -> None:
    seconds = {"1h": 3600}
    if interval not in seconds:
        raise ValueError("EMA200 slope p75 experiment currently supports only 1h")
    expected = int((window.test_end - window.test_start).total_seconds() / seconds[interval])
    if len(test_candles) != expected:
        raise ValueError(
            f"Incomplete test window {window.index}: expected={expected} actual={len(test_candles)}"
        )
    for previous, current in zip(test_candles, test_candles[1:]):
        if (current["open_time"] - previous["open_time"]).total_seconds() != seconds[interval]:
            raise ValueError(f"Time gap in test window {window.index}")


def run_ema200_slope_train_p75_walk_forward(
    *,
    candles: list[dict[str, Any]],
    symbol: str,
    interval: str,
    start,
    end,
    config: WalkForwardConfig | None = None,
) -> EMA200SlopeP75WalkForwardResult:
    wf_config = config or WalkForwardConfig()
    enriched = add_ema200_slope_10(candles)
    windows = generate_walk_forward_windows(start, end, wf_config)

    window_results: list[WalkForwardWindowResult] = []
    thresholds: list[WindowThreshold] = []

    for window in windows:
        threshold, opportunity_count = derive_train_p75_threshold(enriched, window)
        thresholds.append(
            WindowThreshold(
                window_index=window.index,
                train_opportunities=opportunity_count,
                threshold=threshold,
            )
        )

        test_candles = [
            candle
            for candle in enriched
            if window.test_start <= candle["open_time"] < window.test_end
        ]
        _validate_test_window(test_candles, window, interval)

        strategy = TrendDCAEMA200SlopeP75Strategy(
            symbols=[symbol], ema200_slope_threshold=threshold
        )
        engine = BacktestEngine(
            config=BacktestConfig(
                initial_balance=wf_config.initial_balance,
                random_seed=wf_config.random_seed,
            )
        )
        backtest = engine.run(
            candles=test_candles,
            strategy=strategy,
            indicator_provider=lambda candle, index: candle["indicators"],
        )
        window_results.append(
            WalkForwardWindowResult(
                window=window,
                candle_count=len(test_candles),
                initial_balance=wf_config.initial_balance,
                final_equity=backtest.portfolio.total_equity,
                total_pnl=backtest.total_pnl,
                total_trades=backtest.total_trades,
                winning_trades=backtest.winning_trades,
                losing_trades=backtest.losing_trades,
                win_rate=backtest.win_rate,
                profit_factor=backtest.profit_factor,
                max_drawdown=backtest.max_drawdown,
            )
        )

    total_pnl = sum((item.total_pnl for item in window_results), Decimal("0"))
    profitable = sum(item.total_pnl > 0 for item in window_results)
    losing = sum(item.total_pnl < 0 for item in window_results)
    result = WalkForwardResult(
        symbol=symbol,
        interval=interval,
        config=wf_config,
        windows=tuple(window_results),
        total_oos_pnl=total_pnl,
        profitable_windows=profitable,
        losing_windows=losing,
        flat_windows=len(window_results) - profitable - losing,
        total_oos_trades=sum(item.total_trades for item in window_results),
    )
    return EMA200SlopeP75WalkForwardResult(result=result, thresholds=tuple(thresholds))
