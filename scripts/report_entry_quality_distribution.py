from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.reporting.entry_quality_diagnostics import build_entry_quality_diagnostics
from app.reporting.entry_quality_distribution import build_distribution_report


def _json_default(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, UUID):
        return str(value)
    return str(value)


def _fmt(value: Decimal | None) -> str:
    return "" if value is None else str(value)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze entry-quality distributions and quartiles")
    parser.add_argument("--run-id", action="append", required=True)
    args = parser.parse_args()

    reports = []
    for raw_run_id in args.run_id:
        base = await build_entry_quality_diagnostics(UUID(raw_run_id))
        report = build_distribution_report(base)
        reports.append(report)

        print()
        print(f"ENTRY QUALITY DISTRIBUTION: {report.symbol}")
        print("=" * (28 + len(report.symbol)))
        print(f"run_id       : {report.run_id}")
        print(f"total_trades : {report.total_trades}")

        for feature in report.features:
            print()
            print(f"FEATURE: {feature.feature}")
            print("-" * (9 + len(feature.feature)))
            print(
                "overall  "
                f"min={_fmt(feature.overall_stats.minimum)} "
                f"p10={_fmt(feature.overall_stats.p10)} "
                f"p25={_fmt(feature.overall_stats.p25)} "
                f"median={_fmt(feature.overall_stats.median)} "
                f"p75={_fmt(feature.overall_stats.p75)} "
                f"p90={_fmt(feature.overall_stats.p90)} "
                f"max={_fmt(feature.overall_stats.maximum)} "
                f"mean={_fmt(feature.overall_stats.mean)} "
                f"std={_fmt(feature.overall_stats.stddev)}"
            )
            print(
                "winner   "
                f"n={feature.winner_stats.count} "
                f"p10={_fmt(feature.winner_stats.p10)} "
                f"p25={_fmt(feature.winner_stats.p25)} "
                f"median={_fmt(feature.winner_stats.median)} "
                f"p75={_fmt(feature.winner_stats.p75)} "
                f"p90={_fmt(feature.winner_stats.p90)} "
                f"mean={_fmt(feature.winner_stats.mean)} "
                f"std={_fmt(feature.winner_stats.stddev)}"
            )
            print(
                "td_loss  "
                f"n={feature.trend_down_loss_stats.count} "
                f"p10={_fmt(feature.trend_down_loss_stats.p10)} "
                f"p25={_fmt(feature.trend_down_loss_stats.p25)} "
                f"median={_fmt(feature.trend_down_loss_stats.median)} "
                f"p75={_fmt(feature.trend_down_loss_stats.p75)} "
                f"p90={_fmt(feature.trend_down_loss_stats.p90)} "
                f"mean={_fmt(feature.trend_down_loss_stats.mean)} "
                f"std={_fmt(feature.trend_down_loss_stats.stddev)}"
            )
            print(
                f"quartile_bounds q25={feature.q25} q50={feature.q50} q75={feature.q75}"
            )
            for bucket in feature.quartiles:
                print(
                    f"{bucket.quartile} trades={bucket.trades} winners={bucket.winners} "
                    f"td_losses={bucket.trend_down_losses} other={bucket.other} "
                    f"winner_rate={bucket.winner_rate} "
                    f"td_loss_rate={bucket.trend_down_loss_rate} "
                    f"avg_pnl={bucket.average_pnl}"
                )

    output_dir = Path("artifacts/diagnostics")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_file = output_dir / f"entry_quality_distribution_{timestamp}.json"
    payload = {
        "metadata": {
            "created_at": datetime.now(UTC),
            "features": [
                "close_to_ema200",
                "ema200_slope_10",
                "ema50_slope_10",
                "regime_confidence",
                "trend_up_age_bars",
            ],
            "percentile_method": "linear interpolation over sorted sample",
            "quartile_rule": "Q1 <= p25; Q2 <= p50; Q3 <= p75; Q4 > p75",
            "quartile_population": "all reconstructed entries for each symbol/run",
        },
        "reports": [asdict(report) for report in reports],
    }
    output_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    print()
    print(f"artifact : {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
