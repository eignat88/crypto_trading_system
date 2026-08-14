from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.backtest.dataset_fingerprint import build_dataset_fingerprint
from app.config.model_versions import (
    EXECUTION_MODEL_VERSION,
    INDICATOR_MODEL_VERSION,
    REGIME_MODEL_VERSION,
)
from app.reporting.breakout_retest_v1_reproduction import (
    FROZEN_END,
    FROZEN_INTERVAL,
    FROZEN_SEED,
    FROZEN_START,
    reproduce_symbol,
)
from app.reporting.engineering_baseline import (
    EngineeringBaseline,
    SymbolEngineeringBaseline,
    baseline_from_dict,
    baseline_to_dict,
    compare_engineering_baselines,
)
from app.strategies.breakout_retest import PARAMETERS_VERSION
from scripts.run_backtest import load_candles

SYMBOLS = ("BTCUSDT", "ETHUSDT")
STRATEGY_NAME = "BreakoutRetest"


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


async def capture_current_baseline(exchange: str = "bybit") -> EngineeringBaseline:
    symbol_results: list[SymbolEngineeringBaseline] = []
    for symbol in SYMBOLS:
        candles = await load_candles(
            exchange,
            symbol,
            FROZEN_INTERVAL,
            FROZEN_START,
            FROZEN_END,
            indicator_model_version=INDICATOR_MODEL_VERSION,
            regime_model_version=REGIME_MODEL_VERSION,
        )
        if len(candles) != 17520:
            raise RuntimeError(
                f"Engineering baseline requires 17520 candles for {symbol}, got {len(candles)}"
            )
        reproduction = reproduce_symbol(candles, symbol)
        if not reproduction.deterministic:
            raise RuntimeError(f"Non-deterministic engineering observation for {symbol}")
        dataset_fingerprint = build_dataset_fingerprint(
            candles,
            indicator_model_version=INDICATOR_MODEL_VERSION,
            regime_model_version=REGIME_MODEL_VERSION,
        )
        symbol_results.append(
            SymbolEngineeringBaseline(
                symbol=symbol,
                candle_count=len(candles),
                dataset_fingerprint=dataset_fingerprint,
                total_trades=reproduction.total_trades,
                total_pnl=reproduction.total_pnl,
                profitable_windows=reproduction.profitable_windows,
                audit_fingerprints=tuple(
                    window.audit_fingerprint for window in reproduction.windows
                ),
            )
        )

    return EngineeringBaseline(
        strategy_name=STRATEGY_NAME,
        parameters_version=PARAMETERS_VERSION,
        interval=FROZEN_INTERVAL,
        period_start=FROZEN_START.isoformat(),
        period_end=FROZEN_END.isoformat(),
        random_seed=FROZEN_SEED,
        indicator_model_version=INDICATOR_MODEL_VERSION,
        regime_model_version=REGIME_MODEL_VERSION,
        execution_model_version=EXECUTION_MODEL_VERSION,
        symbols=tuple(symbol_results),
    )


def _write_candidate(baseline: EngineeringBaseline) -> Path:
    output_dir = Path("artifacts/engineering")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = output_dir / f"versioned_engineering_baseline_candidate_{timestamp}.json"
    payload = {
        "metadata": {
            "created_at": datetime.now(UTC).isoformat(),
            "git_commit": _git_commit(),
            "purpose": "engineering reproducibility only; not strategy performance validation",
            "independent_validation_opened": False,
        },
        "baseline": baseline_to_dict(baseline),
    }
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return output


def _load_baseline(path: Path) -> EngineeringBaseline:
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    baseline_payload = payload.get("baseline", payload)
    if not isinstance(baseline_payload, dict):
        raise ValueError("Baseline JSON must contain an object")
    return baseline_from_dict(baseline_payload)


def _print_baseline(baseline: EngineeringBaseline) -> None:
    print("VERSIONED ENGINEERING BASELINE")
    print("==============================")
    print(f"strategy              : {baseline.strategy_name}")
    print(f"parameters_version    : {baseline.parameters_version}")
    print(f"period                : {baseline.period_start} -> {baseline.period_end}")
    print(f"interval              : {baseline.interval}")
    print(f"indicator_model       : {baseline.indicator_model_version}")
    print(f"regime_model          : {baseline.regime_model_version}")
    print(f"execution_model       : {baseline.execution_model_version}")
    for item in baseline.symbols:
        print()
        print(f"{item.symbol}")
        print(f"  candles             : {item.candle_count}")
        print(f"  dataset_fingerprint : {item.dataset_fingerprint}")
        print(f"  trades              : {item.total_trades}")
        print(f"  pnl                 : {item.total_pnl}")
        print(f"  profitable_windows  : {item.profitable_windows}")
        print(f"  window_audits       : {len(item.audit_fingerprints)}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture or verify the versioned engineering baseline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--exchange", default="bybit")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--baseline", required=True, type=Path)
    verify_parser.add_argument("--exchange", default="bybit")

    args = parser.parse_args()
    actual = await capture_current_baseline(args.exchange)
    _print_baseline(actual)

    if args.command == "capture":
        candidate = _write_candidate(actual)
        print()
        print("status                : CANDIDATE_CAPTURED")
        print(f"candidate             : {candidate}")
        print("performance_claim     : NO")
        return

    expected = _load_baseline(args.baseline)
    check = compare_engineering_baselines(expected, actual)
    print()
    print(f"status                : {'PASS' if check.compatible else 'FAIL'}")
    if check.reasons:
        print("reasons:")
        for reason in check.reasons:
            print(f"  - {reason}")
        raise RuntimeError("Versioned engineering baseline verification failed")


if __name__ == "__main__":
    asyncio.run(main())
