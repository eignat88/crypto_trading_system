from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.reporting.breakout_retest_v1_reproduction import (
    EXPECTED,
    EXPECTED_COMBINED_PNL,
    EXPECTED_COMBINED_TRADES,
    FROZEN_END,
    FROZEN_INITIAL_BALANCE,
    FROZEN_INTERVAL,
    FROZEN_SEED,
    FROZEN_START,
    FROZEN_STEP_DAYS,
    FROZEN_TEST_DAYS,
    FROZEN_TRAIN_DAYS,
    assert_gate_passed,
    build_gate_result,
    reproduce_symbol,
)
from scripts.run_backtest import load_candles


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail-closed frozen Breakout Retest v1 reproduction gate"
    )
    parser.add_argument("--exchange", default="bybit")
    args = parser.parse_args()

    reproductions = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        candles = await load_candles(
            args.exchange,
            symbol,
            FROZEN_INTERVAL,
            FROZEN_START,
            FROZEN_END,
        )
        result = reproduce_symbol(candles, symbol)
        reproductions.append(result)

        expected = EXPECTED[symbol]
        print()
        print(f"BREAKOUT RETEST V1 REPRODUCTION: {symbol}")
        print("=" * (34 + len(symbol)))
        print(f"expected_trades       : {expected['trades']}")
        print(f"actual_trades         : {result.total_trades}")
        print(f"expected_pnl          : {expected['pnl']}")
        print(f"actual_pnl            : {result.total_pnl}")
        print(f"profitable_windows    : {result.profitable_windows}")
        print(f"deterministic         : {result.deterministic}")
        print(f"expected_metrics_match: {result.expected_metrics_match}")
        print("WINDOW AUDIT")
        print("------------")
        for window in result.windows:
            print(
                f"w{window.window_index:02d} "
                f"pnl={window.total_pnl} trades={window.total_trades} "
                f"fingerprint={window.audit_fingerprint}"
            )

    gate = build_gate_result(reproductions)
    print()
    print("COMBINED BREAKOUT RETEST V1 REPRODUCTION GATE")
    print("=============================================")
    print(f"expected_trades       : {EXPECTED_COMBINED_TRADES}")
    print(f"actual_trades         : {gate.combined_trades}")
    print(f"expected_pnl          : {EXPECTED_COMBINED_PNL}")
    print(f"actual_pnl            : {gate.combined_pnl}")
    print(f"deterministic         : {gate.deterministic}")
    print(f"combined_match        : {gate.combined_expected_match}")
    print(f"GATE_PASS             : {gate.passed}")

    output_dir = Path("artifacts/engineering")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact = output_dir / f"breakout_retest_v1_reproduction_{timestamp}.json"
    artifact.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(timezone.utc),
                    "purpose": "engineering reproduction only; no v2 validation",
                    "strategy": "breakout_retest_v1",
                    "exchange": args.exchange,
                    "interval": FROZEN_INTERVAL,
                    "start": FROZEN_START,
                    "end": FROZEN_END,
                    "train_days": FROZEN_TRAIN_DAYS,
                    "test_days": FROZEN_TEST_DAYS,
                    "step_days": FROZEN_STEP_DAYS,
                    "initial_balance": FROZEN_INITIAL_BALANCE,
                    "seed": FROZEN_SEED,
                    "v2_imported_or_executed": False,
                    "independent_validation_opened": False,
                },
                "expected": {
                    "symbols": EXPECTED,
                    "combined_trades": EXPECTED_COMBINED_TRADES,
                    "combined_pnl": EXPECTED_COMBINED_PNL,
                },
                "result": asdict(gate),
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    print(f"artifact              : {artifact}")

    assert_gate_passed(gate)


if __name__ == "__main__":
    asyncio.run(main())
