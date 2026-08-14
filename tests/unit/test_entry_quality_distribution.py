from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from app.reporting.entry_quality_diagnostics import EntryQualityRecord
from app.reporting.entry_quality_distribution import (
    analyze_feature,
    distribution_stats,
    percentile,
)

UTC = UTC


def _record(*, value: str, group: str, pnl: str, age: int = 10) -> EntryQualityRecord:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return EntryQualityRecord(
        run_id=uuid4(),
        symbol="BTCUSDT",
        outcome_group=group,
        exit_reason="test",
        entry_signal_time=now,
        entry_fill_time=now,
        entry_signal_price=Decimal("100"),
        entry_fill_price=Decimal("100"),
        weighted_entry_price=Decimal("100"),
        dca_count=0,
        rsi=Decimal("42"),
        ema_20=Decimal("99"),
        ema_50=Decimal("98"),
        ema_200=Decimal("97"),
        close_to_ema20=Decimal("0.01"),
        close_to_ema50=Decimal("0.02"),
        close_to_ema200=Decimal(value),
        ema20_slope_10=Decimal("0.001"),
        ema50_slope_10=Decimal("0.002"),
        ema200_slope_10=Decimal(value),
        atr=Decimal("1"),
        atr_pct=Decimal("0.01"),
        volatility=Decimal("0.1"),
        regime_confidence=Decimal(value),
        trend_up_age_bars=age,
        trend_up_age_censored=False,
        time_to_trend_down_hours=None,
        trend_down_before_exit=False,
        exit_time=now,
        realized_pnl=Decimal(pnl),
    )


def test_percentile_uses_linear_interpolation():
    values = [Decimal("0"), Decimal("10"), Decimal("20"), Decimal("30")]
    assert percentile(values, Decimal("0.25")) == Decimal("7.50")
    assert percentile(values, Decimal("0.50")) == Decimal("15.0")
    assert percentile(values, Decimal("0.75")) == Decimal("22.50")


def test_distribution_stats_use_population_stddev():
    stats = distribution_stats([Decimal("1"), Decimal("2"), Decimal("3")])
    assert stats.count == 3
    assert stats.minimum == Decimal("1")
    assert stats.maximum == Decimal("3")
    assert stats.mean == Decimal("2")
    assert abs(stats.stddev - Decimal("0.8164965809277260327324280249")) < Decimal("1E-27")


def test_quartile_assignment_uses_fixed_lower_bucket_boundary_rule():
    records = [
        _record(value="1", group="OTHER", pnl="0"),
        _record(value="2", group="TREND_DOWN_LOSS", pnl="-1"),
        _record(value="3", group="WINNER", pnl="1"),
        _record(value="4", group="WINNER", pnl="2"),
        _record(value="5", group="OTHER", pnl="0"),
    ]
    result = analyze_feature(records, "close_to_ema200")
    assert result.q25 == Decimal("2")
    assert result.q50 == Decimal("3")
    assert result.q75 == Decimal("4")
    assert [bucket.trades for bucket in result.quartiles] == [2, 1, 1, 1]
    assert result.quartiles[0].trend_down_losses == 1
    assert result.quartiles[1].winners == 1
    assert result.quartiles[2].winners == 1


def test_quartile_rates_and_average_pnl_are_calculated_from_all_entries():
    records = [
        _record(value="1", group="TREND_DOWN_LOSS", pnl="-2"),
        _record(value="2", group="WINNER", pnl="1"),
        _record(value="3", group="OTHER", pnl="0"),
        _record(value="4", group="WINNER", pnl="3"),
    ]
    result = analyze_feature(records, "ema200_slope_10")
    total = sum(bucket.trades for bucket in result.quartiles)
    assert total == 4
    assert sum(bucket.winners for bucket in result.quartiles) == 2
    assert sum(bucket.trend_down_losses for bucket in result.quartiles) == 1
    q1 = result.quartiles[0]
    assert q1.trades == 1
    assert q1.trend_down_loss_rate == Decimal("1")
    assert q1.average_pnl == Decimal("-2")


def test_trend_up_age_is_supported_as_decimal_distribution():
    records = [
        _record(value="0.1", group="WINNER", pnl="1", age=10),
        _record(value="0.2", group="TREND_DOWN_LOSS", pnl="-1", age=20),
        _record(value="0.3", group="OTHER", pnl="0", age=30),
        _record(value="0.4", group="WINNER", pnl="1", age=40),
    ]
    result = analyze_feature(records, "trend_up_age_bars")
    assert result.overall_stats.median == Decimal("25.0")
    assert result.winner_stats.count == 2
    assert result.trend_down_loss_stats.count == 1
