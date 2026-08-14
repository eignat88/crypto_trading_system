from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine, BacktestResult
from app.backtest.walk_forward import WalkForwardConfig, generate_walk_forward_windows
from app.strategies.breakout_retest import PARAMETERS_VERSION, BreakoutRetestStrategy

FROZEN_START = datetime(2024, 8, 10, tzinfo=UTC)
FROZEN_END = datetime(2026, 8, 10, tzinfo=UTC)
FROZEN_INTERVAL = "1h"
FROZEN_TRAIN_DAYS = 180
FROZEN_TEST_DAYS = 60
FROZEN_STEP_DAYS = 60
FROZEN_INITIAL_BALANCE = Decimal("500")
FROZEN_SEED = 42
PNL_TOLERANCE = Decimal("1E-24")

EXPECTED = {
    "BTCUSDT": {
        "trades": 49,
        "pnl": Decimal("-0.1391016840064235879634907285"),
    },
    "ETHUSDT": {
        "trades": 64,
        "pnl": Decimal("-3.153621560329388837431488648"),
    },
}
EXPECTED_COMBINED_TRADES = 113
EXPECTED_COMBINED_PNL = Decimal("-3.292723244335812425394979376")


@dataclass(frozen=True)
class WindowReproduction:
    window_index: int
    test_start: datetime
    test_end: datetime
    candle_count: int
    total_trades: int
    total_pnl: Decimal
    audit_fingerprint: str


@dataclass(frozen=True)
class SymbolReproduction:
    symbol: str
    parameters_version: str
    total_trades: int
    total_pnl: Decimal
    profitable_windows: int
    windows: tuple[WindowReproduction, ...]
    deterministic: bool
    expected_metrics_match: bool


@dataclass(frozen=True)
class ReproductionGateResult:
    symbols: tuple[SymbolReproduction, ...]
    combined_trades: int
    combined_pnl: Decimal
    combined_expected_match: bool
    deterministic: bool
    passed: bool


def frozen_walk_forward_config() -> WalkForwardConfig:
    return WalkForwardConfig(
        train_days=FROZEN_TRAIN_DAYS,
        test_days=FROZEN_TEST_DAYS,
        step_days=FROZEN_STEP_DAYS,
        initial_balance=FROZEN_INITIAL_BALANCE,
        random_seed=FROZEN_SEED,
    )


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Audit datetime must be timezone-aware")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    if is_dataclass(value):
        return _canonical(asdict(value))
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def audit_fingerprint(result: BacktestResult) -> str:
    """Fingerprint deterministic decision/execution artifacts, not runtime logging."""
    payload = {
        "total_trades": result.total_trades,
        "winning_trades": result.winning_trades,
        "losing_trades": result.losing_trades,
        "total_pnl": result.total_pnl,
        "max_drawdown": result.max_drawdown,
        "signals": result.signals,
        "risk_decisions": result.risk_decisions,
        "orders": result.orders,
        "fills": result.fills,
    }
    encoded = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_frozen_candles(candles: list[dict[str, Any]], symbol: str) -> None:
    if symbol not in EXPECTED:
        raise ValueError(f"Unsupported frozen symbol: {symbol}")
    if not candles:
        raise ValueError(f"No candles supplied for {symbol}")
    previous: datetime | None = None
    for candle in candles:
        timestamp = candle.get("open_time")
        if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
            raise ValueError("All candle open_time values must be timezone-aware datetime")
        timestamp = timestamp.astimezone(UTC)
        if not FROZEN_START <= timestamp < FROZEN_END:
            raise ValueError(
                f"Candle outside frozen reproduction range: {timestamp.isoformat()}"
            )
        if str(candle.get("symbol")) != symbol:
            raise ValueError(f"Unexpected symbol in candle stream: {candle.get('symbol')}")
        if previous is not None and timestamp <= previous:
            raise ValueError("Candles must be strictly increasing by open_time")
        previous = timestamp


def _run_once(candles: list[dict[str, Any]], symbol: str) -> tuple[WindowReproduction, ...]:
    config = frozen_walk_forward_config()
    windows = generate_walk_forward_windows(FROZEN_START, FROZEN_END, config)
    reproduced: list[WindowReproduction] = []

    for window in windows:
        test_candles = [
            candle
            for candle in candles
            if window.test_start <= candle["open_time"] < window.test_end
        ]
        expected_count = FROZEN_TEST_DAYS * 24
        if len(test_candles) != expected_count:
            raise ValueError(
                f"Incomplete frozen test window {window.index} for {symbol}: "
                f"expected={expected_count} actual={len(test_candles)}"
            )
        for previous, current in zip(test_candles, test_candles[1:]):
            if (current["open_time"] - previous["open_time"]).total_seconds() != 3600:
                raise ValueError(
                    f"Hourly gap in frozen test window {window.index}: "
                    f"{previous['open_time']} -> {current['open_time']}"
                )

        strategy = BreakoutRetestStrategy([symbol])
        engine = BacktestEngine(
            config=BacktestConfig(
                initial_balance=FROZEN_INITIAL_BALANCE,
                random_seed=FROZEN_SEED,
            )
        )
        result = engine.run(
            candles=test_candles,
            strategy=strategy,
            indicator_provider=lambda candle, index: candle["indicators"],
        )
        reproduced.append(
            WindowReproduction(
                window_index=window.index,
                test_start=window.test_start,
                test_end=window.test_end,
                candle_count=len(test_candles),
                total_trades=result.total_trades,
                total_pnl=result.total_pnl,
                audit_fingerprint=audit_fingerprint(result),
            )
        )

    return tuple(reproduced)


def reproduce_symbol(candles: list[dict[str, Any]], symbol: str) -> SymbolReproduction:
    validate_frozen_candles(candles, symbol)
    first = _run_once(candles, symbol)
    second = _run_once(candles, symbol)

    deterministic = first == second
    total_trades = sum(window.total_trades for window in first)
    total_pnl = sum((window.total_pnl for window in first), Decimal("0"))
    profitable_windows = sum(1 for window in first if window.total_pnl > 0)
    expected = EXPECTED[symbol]
    expected_metrics_match = (
        total_trades == expected["trades"]
        and abs(total_pnl - expected["pnl"]) <= PNL_TOLERANCE
    )

    return SymbolReproduction(
        symbol=symbol,
        parameters_version=PARAMETERS_VERSION,
        total_trades=total_trades,
        total_pnl=total_pnl,
        profitable_windows=profitable_windows,
        windows=first,
        deterministic=deterministic,
        expected_metrics_match=expected_metrics_match,
    )


def build_gate_result(symbols: list[SymbolReproduction]) -> ReproductionGateResult:
    if {item.symbol for item in symbols} != set(EXPECTED):
        raise ValueError("Reproduction gate requires exactly BTCUSDT and ETHUSDT")
    combined_trades = sum(item.total_trades for item in symbols)
    combined_pnl = sum((item.total_pnl for item in symbols), Decimal("0"))
    deterministic = all(item.deterministic for item in symbols)
    symbol_expected = all(item.expected_metrics_match for item in symbols)
    combined_expected_match = (
        combined_trades == EXPECTED_COMBINED_TRADES
        and abs(combined_pnl - EXPECTED_COMBINED_PNL) <= PNL_TOLERANCE
    )
    passed = deterministic and symbol_expected and combined_expected_match
    return ReproductionGateResult(
        symbols=tuple(symbols),
        combined_trades=combined_trades,
        combined_pnl=combined_pnl,
        combined_expected_match=combined_expected_match,
        deterministic=deterministic,
        passed=passed,
    )


def assert_gate_passed(result: ReproductionGateResult) -> None:
    if result.passed:
        return
    failures: list[str] = []
    for symbol in result.symbols:
        if not symbol.expected_metrics_match:
            failures.append(
                f"{symbol.symbol} expected metrics mismatch: "
                f"trades={symbol.total_trades} pnl={symbol.total_pnl}"
            )
        if not symbol.deterministic:
            failures.append(f"{symbol.symbol} deterministic audit mismatch")
    if not result.combined_expected_match:
        failures.append(
            f"combined expected metrics mismatch: trades={result.combined_trades} "
            f"pnl={result.combined_pnl}"
        )
    raise RuntimeError("Breakout Retest v1 reproduction gate failed: " + "; ".join(failures))
