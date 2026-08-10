from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.reporting.trend_momentum_decay import HORIZONS, build_trend_momentum_decay

UTC = timezone.utc


def _candles(count: int = 80) -> list[dict]:
    rows = []
    for i in range(count):
        base = Decimal("100") + Decimal(i)
        rows.append(
            {
                "open_time": datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i),
                "close": base,
                "indicators": {
                    "ema_20": base - Decimal("1") + Decimal(i) / Decimal("100"),
                    "ema_50": base - Decimal("2") + Decimal(i) / Decimal("200"),
                    "ema_200": base - Decimal("3") + Decimal(i) / Decimal("400"),
                    "regime_confidence": Decimal("0.60") + Decimal(i) / Decimal("1000"),
                },
            }
        )
    return rows


def _trade(candles: list[dict], index: int, group: str, pnl: str):
    return SimpleNamespace(
        symbol="BTCUSDT",
        window_index=1,
        filter_group=group,
        entry_signal_time=candles[index]["open_time"],
        realized_pnl=Decimal(pnl),
    )


def _counterfactual(candles: list[dict]):
    trades = (
        _trade(candles, 50, "FILTERED_WINNER", "0.5"),
        _trade(candles, 60, "FILTERED_TD_LOSS", "-0.7"),
        _trade(candles, 65, "PASS_WINNER", "0.3"),
    )
    return SimpleNamespace(
        symbol="BTCUSDT",
        trades=trades,
        filtered_winner=1,
        filtered_td_loss=1,
    )


def test_builds_only_target_filtered_groups_for_all_fixed_horizons():
    candles = _candles()
    report = build_trend_momentum_decay(candles=candles, counterfactual=_counterfactual(candles))

    assert report.source_filtered_winners == 1
    assert report.source_filtered_td_losses == 1
    assert len(report.records) == 2 * len(HORIZONS)
    assert {item.filter_group for item in report.records} == {"FILTERED_WINNER", "FILTERED_TD_LOSS"}
    assert {item.horizon_hours for item in report.records} == set(HORIZONS)
    assert len(report.summaries) == 2 * len(HORIZONS)


def test_delta_is_entry_value_minus_exact_horizon_past_value():
    candles = _candles()
    report = build_trend_momentum_decay(
        candles=candles,
        counterfactual=_counterfactual(candles),
        horizons=(12,),
    )
    record = next(item for item in report.records if item.filter_group == "FILTERED_WINNER")

    assert record.regime_confidence_now == Decimal("0.650")
    assert record.regime_confidence_past == Decimal("0.638")
    assert record.regime_confidence_delta == Decimal("0.012")
    assert record.ema20_slope_delta == record.ema20_slope_now - record.ema20_slope_past
    assert record.close_to_ema200_delta == record.close_to_ema200_now - record.close_to_ema200_past


def test_summary_decay_rate_counts_negative_deltas():
    candles = _candles()
    # Winner entry is index 50. For horizon=6, the past slope is evaluated at
    # index 44. Make slope(44)=(130-100)/100=0.30 and
    # slope(50)=(125-120)/120~=0.0417, so delta is strictly negative.
    candles[35]["indicators"]["ema_50"] = Decimal("100")
    candles[41]["indicators"]["ema_50"] = Decimal("120")
    candles[44]["indicators"]["ema_50"] = Decimal("130")
    candles[50]["indicators"]["ema_50"] = Decimal("125")

    report = build_trend_momentum_decay(
        candles=candles,
        counterfactual=_counterfactual(candles),
        horizons=(6,),
    )
    winner_record = next(
        item for item in report.records if item.filter_group == "FILTERED_WINNER"
    )
    winner_summary = next(
        item for item in report.summaries if item.group == "FILTERED_WINNER"
    )

    assert winner_record.ema50_slope_delta is not None
    assert winner_record.ema50_slope_delta < 0
    assert winner_summary.trades == 1
    assert winner_summary.average_pnl == Decimal("0.5")
    assert winner_summary.ema50_decay_count == 1
    assert winner_summary.ema50_decay_rate == Decimal("1")


def test_rejects_non_positive_horizon():
    candles = _candles()
    with pytest.raises(ValueError, match="Horizons must be positive"):
        build_trend_momentum_decay(
            candles=candles,
            counterfactual=_counterfactual(candles),
            horizons=(0,),
        )


def test_rejects_insufficient_causal_history():
    candles = _candles(40)
    trade = _trade(candles, 20, "FILTERED_WINNER", "0.5")
    counterfactual = SimpleNamespace(
        symbol="BTCUSDT",
        trades=(trade,),
        filtered_winner=1,
        filtered_td_loss=0,
    )

    with pytest.raises(ValueError, match="Insufficient causal history"):
        build_trend_momentum_decay(
            candles=candles,
            counterfactual=counterfactual,
            horizons=(12,),
        )
