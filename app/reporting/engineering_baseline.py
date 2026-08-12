from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SymbolEngineeringBaseline:
    symbol: str
    candle_count: int
    dataset_fingerprint: str
    total_trades: int
    total_pnl: Decimal
    profitable_windows: int
    audit_fingerprints: tuple[str, ...]


@dataclass(frozen=True)
class EngineeringBaseline:
    strategy_name: str
    parameters_version: str
    interval: str
    period_start: str
    period_end: str
    random_seed: int
    indicator_model_version: str
    regime_model_version: str
    execution_model_version: str
    symbols: tuple[SymbolEngineeringBaseline, ...]


@dataclass(frozen=True)
class EngineeringBaselineCheck:
    compatible: bool
    reasons: tuple[str, ...]


def baseline_from_dict(payload: dict[str, Any]) -> EngineeringBaseline:
    symbols = tuple(
        SymbolEngineeringBaseline(
            symbol=str(item["symbol"]),
            candle_count=int(item["candle_count"]),
            dataset_fingerprint=str(item["dataset_fingerprint"]),
            total_trades=int(item["total_trades"]),
            total_pnl=Decimal(str(item["total_pnl"])),
            profitable_windows=int(item["profitable_windows"]),
            audit_fingerprints=tuple(str(v) for v in item["audit_fingerprints"]),
        )
        for item in payload["symbols"]
    )
    return EngineeringBaseline(
        strategy_name=str(payload["strategy_name"]),
        parameters_version=str(payload["parameters_version"]),
        interval=str(payload["interval"]),
        period_start=str(payload["period_start"]),
        period_end=str(payload["period_end"]),
        random_seed=int(payload["random_seed"]),
        indicator_model_version=str(payload["indicator_model_version"]),
        regime_model_version=str(payload["regime_model_version"]),
        execution_model_version=str(payload["execution_model_version"]),
        symbols=symbols,
    )


def baseline_to_dict(baseline: EngineeringBaseline) -> dict[str, Any]:
    return {
        "strategy_name": baseline.strategy_name,
        "parameters_version": baseline.parameters_version,
        "interval": baseline.interval,
        "period_start": baseline.period_start,
        "period_end": baseline.period_end,
        "random_seed": baseline.random_seed,
        "indicator_model_version": baseline.indicator_model_version,
        "regime_model_version": baseline.regime_model_version,
        "execution_model_version": baseline.execution_model_version,
        "symbols": [
            {
                "symbol": item.symbol,
                "candle_count": item.candle_count,
                "dataset_fingerprint": item.dataset_fingerprint,
                "total_trades": item.total_trades,
                "total_pnl": str(item.total_pnl),
                "profitable_windows": item.profitable_windows,
                "audit_fingerprints": list(item.audit_fingerprints),
            }
            for item in baseline.symbols
        ],
    }


def compare_engineering_baselines(
    expected: EngineeringBaseline,
    actual: EngineeringBaseline,
) -> EngineeringBaselineCheck:
    reasons: list[str] = []
    scalar_fields = (
        "strategy_name",
        "parameters_version",
        "interval",
        "period_start",
        "period_end",
        "random_seed",
        "indicator_model_version",
        "regime_model_version",
        "execution_model_version",
    )
    for field in scalar_fields:
        expected_value = getattr(expected, field)
        actual_value = getattr(actual, field)
        if expected_value != actual_value:
            reasons.append(f"{field} mismatch: expected={expected_value} actual={actual_value}")

    expected_symbols = {item.symbol: item for item in expected.symbols}
    actual_symbols = {item.symbol: item for item in actual.symbols}
    if set(expected_symbols) != set(actual_symbols):
        reasons.append(
            f"symbol set mismatch: expected={sorted(expected_symbols)} actual={sorted(actual_symbols)}"
        )
    else:
        for symbol in sorted(expected_symbols):
            expected_item = expected_symbols[symbol]
            actual_item = actual_symbols[symbol]
            for field in (
                "candle_count",
                "dataset_fingerprint",
                "total_trades",
                "total_pnl",
                "profitable_windows",
                "audit_fingerprints",
            ):
                expected_value = getattr(expected_item, field)
                actual_value = getattr(actual_item, field)
                if expected_value != actual_value:
                    reasons.append(
                        f"{symbol}.{field} mismatch: expected={expected_value} actual={actual_value}"
                    )

    return EngineeringBaselineCheck(compatible=not reasons, reasons=tuple(reasons))
