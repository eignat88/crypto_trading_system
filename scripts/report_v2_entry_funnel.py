from __future__ import annotations

import argparse
import asyncio
import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.backtest.walk_forward import WalkForwardConfig
from app.reporting.v2_entry_funnel import V2EntryFunnelReport, run_v2_entry_funnel
from scripts.run_backtest import load_candles, parse_datetime

EXPECTED_BASELINE = {
    "BTCUSDT": {
        "pnl": Decimal("-1.919472385900019863816920150"),
        "trades": 54,
    },
    "ETHUSDT": {
        "pnl": Decimal("-3.468563029505904349952368764"),
        "trades": 66,
    },
}
EXPECTED_V2 = {
    "BTCUSDT": {
        "pnl": Decimal("-2.079653300192381287310302995"),
        "trades": 23,
    },
    "ETHUSDT": {
        "pnl": Decimal("1.575541754040755349362542211"),
        "trades": 15,
    },
}
PNL_TOLERANCE = Decimal("1E-12")


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    return str(value)


def _validate_known_result(report: V2EntryFunnelReport) -> None:
    expected_base = EXPECTED_BASELINE.get(report.symbol)
    expected_v2 = EXPECTED_V2.get(report.symbol)
    if expected_base is None or expected_v2 is None:
        raise ValueError(f"No frozen reproducibility gate for {report.symbol}")
    if abs(report.baseline_oos_pnl - expected_base["pnl"]) > PNL_TOLERANCE:
        raise ValueError(
            f"Baseline PnL gate failed for {report.symbol}: "
            f"actual={report.baseline_oos_pnl} expected={expected_base['pnl']}"
        )
    if report.baseline_trades != expected_base["trades"]:
        raise ValueError(
            f"Baseline trade gate failed for {report.symbol}: "
            f"actual={report.baseline_trades} expected={expected_base['trades']}"
        )
    if abs(report.v2_oos_pnl - expected_v2["pnl"]) > PNL_TOLERANCE:
        raise ValueError(
            f"V2 PnL gate failed for {report.symbol}: "
            f"actual={report.v2_oos_pnl} expected={expected_v2['pnl']}"
        )
    if report.v2_trades != expected_v2["trades"]:
        raise ValueError(
            f"V2 trade gate failed for {report.symbol}: "
            f"actual={report.v2_trades} expected={expected_v2['trades']}"
        )


def _print_status_counts(title: str, counts: dict[str, int]) -> None:
    print(title)
    print("-" * len(title))
    if not counts:
        print("  none")
        return
    total = sum(counts.values())
    for key, count in counts.items():
        rate = Decimal(count) / Decimal(total) if total else Decimal("0")
        print(f"  {key:34s}: {count:3d} ({rate})")


def _print_report(report: V2EntryFunnelReport) -> None:
    print()
    print(f"V2 ENTRY FUNNEL: {report.symbol}")
    print("=" * (17 + len(report.symbol)))
    print(f"baseline_oos_pnl          : {report.baseline_oos_pnl}")
    print(f"v2_oos_pnl                : {report.v2_oos_pnl}")
    print(f"baseline_trades           : {report.baseline_trades}")
    print(f"v2_trades                 : {report.v2_trades}")
    print(f"baseline_winners          : {report.baseline_winners}")
    print(f"baseline_losing_or_flat   : {report.baseline_losing_or_flat}")
    print()
    print("FUNNEL")
    print("------")
    print(f"setups_armed              : {report.setups_armed}")
    print(f"rsi_crosses_while_armed   : {report.rsi_crosses_while_armed}")
    print(f"rsi_crosses_above_ema20   : {report.rsi_crosses_above_ema20}")
    print(f"volatility_blocks         : {report.rsi_crosses_blocked_volatility}")
    print(f"confirmed_signals         : {report.confirmed_signals}")
    print(f"confirmed_fills           : {report.confirmed_fills}")
    print(f"v2_closed_trades          : {report.v2_trades}")
    print()
    print("CANCELLATIONS")
    print("-------------")
    print(f"regime                    : {report.cancelled_regime}")
    print(f"close<=EMA200             : {report.cancelled_close_ema200}")
    print(f"EMA50<=EMA200             : {report.cancelled_ema50_ema200}")
    print(f"position                  : {report.cancelled_position}")
    print(f"timeout                   : {report.cancelled_timeout}")
    print(f"open_at_end               : {report.open_at_end}")
    print(f"waiting_evaluations       : {report.waiting_evaluations}")
    print()
    print(f"missed_baseline_winners   : {len(report.missed_baseline_winners)}")
    print(f"missed_baseline_losses    : {len(report.missed_baseline_losses)}")
    print()
    _print_status_counts("MISSED WINNER STATUS", report.missed_winner_status_counts)
    print()
    _print_status_counts("MISSED LOSS STATUS", report.missed_loss_status_counts)
    print()
    print("WINDOW FUNNEL")
    print("-------------")
    for item in report.windows:
        print(
            f"w{item.window_index:02d} "
            f"base={item.baseline_trades}/{item.baseline_winners}W "
            f"v2={item.v2_trades} "
            f"armed={item.setups_armed} confirmed={item.confirmed_signals} "
            f"cancel_regime={item.cancelled_regime} "
            f"cancel_ema200={item.cancelled_close_ema200} "
            f"cancel_ema50={item.cancelled_ema50_ema200} "
            f"cancel_timeout={item.cancelled_timeout} "
            f"cross={item.rsi_crosses_while_armed} "
            f"cross_ema20={item.rsi_crosses_above_ema20}"
        )


def _write_csv(path: Path, reports: list[V2EntryFunnelReport]) -> None:
    fields = [
        "symbol",
        "kind",
        "window_index",
        "entry_signal_time",
        "entry_fill_time",
        "pnl",
        "exit_reason",
        "outcome",
        "v2_status",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for report in reports:
            for kind, items in (
                ("MISSED_WINNER", report.missed_baseline_winners),
                ("MISSED_LOSS", report.missed_baseline_losses),
            ):
                for item in items:
                    writer.writerow(
                        {
                            "symbol": report.symbol,
                            "kind": kind,
                            "window_index": item.window_index,
                            "entry_signal_time": item.entry_signal_time.isoformat(),
                            "entry_fill_time": item.entry_fill_time.isoformat(),
                            "pnl": str(item.pnl),
                            "exit_reason": item.exit_reason,
                            "outcome": item.outcome,
                            "v2_status": item.v2_status,
                        }
                    )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only funnel diagnostics for Trend Pullback Confirmation v1"
    )
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        choices=["BTCUSDT", "ETHUSDT"],
    )
    parser.add_argument("--exchange", default="bybit")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--train-days", type=int, default=180)
    parser.add_argument("--test-days", type=int, default=60)
    parser.add_argument("--step-days", type=int, default=60)
    parser.add_argument("--initial-balance", type=Decimal, default=Decimal("500"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    start = parse_datetime(args.start)
    end = parse_datetime(args.end)
    config = WalkForwardConfig(
        train_days=args.train_days,
        test_days=args.test_days,
        step_days=args.step_days,
        initial_balance=args.initial_balance,
        random_seed=args.seed,
    )

    reports: list[V2EntryFunnelReport] = []
    for symbol in args.symbols:
        candles = await load_candles(args.exchange, symbol, args.interval, start, end)
        report = run_v2_entry_funnel(
            candles=candles,
            symbol=symbol,
            interval=args.interval,
            start=start,
            end=end,
            config=config,
        )
        _validate_known_result(report)
        reports.append(report)
        _print_report(report)

    print()
    print("COMBINED V2 ENTRY FUNNEL")
    print("========================")
    print(f"symbols                   : {','.join(args.symbols)}")
    print(f"setups_armed              : {sum(r.setups_armed for r in reports)}")
    print(f"confirmed_signals         : {sum(r.confirmed_signals for r in reports)}")
    print(f"confirmed_fills           : {sum(r.confirmed_fills for r in reports)}")
    print(f"missed_baseline_winners   : {sum(len(r.missed_baseline_winners) for r in reports)}")
    print(f"missed_baseline_losses    : {sum(len(r.missed_baseline_losses) for r in reports)}")
    print(f"cancelled_timeout         : {sum(r.cancelled_timeout for r in reports)}")
    print(f"cancelled_regime          : {sum(r.cancelled_regime for r in reports)}")

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"v2_entry_funnel_{timestamp}.json"
    csv_path = output_dir / f"v2_entry_funnel_{timestamp}.csv"
    json_path.write_text(
        json.dumps(
            {
                "metadata": {
                    "created_at": datetime.now(UTC),
                    "strategy": "trend_pullback_confirmation_v1",
                    "diagnostic": "V2_ENTRY_FUNNEL",
                    "exchange": args.exchange,
                    "symbols": args.symbols,
                    "interval": args.interval,
                    "start": start,
                    "end": end,
                    "walk_forward_config": asdict(config),
                    "baseline_miss_winner_definition": "baseline realized_pnl > 0",
                },
                "reports": [asdict(report) for report in reports],
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )
    _write_csv(csv_path, reports)
    print(f"json_artifact             : {json_path}")
    print(f"csv_artifact              : {csv_path}")


if __name__ == "__main__":
    asyncio.run(main())
