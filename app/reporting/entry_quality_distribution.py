from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.reporting.entry_quality_diagnostics import EntryQualityRecord, EntryQualityReport

FEATURES = (
    "close_to_ema200",
    "ema200_slope_10",
    "ema50_slope_10",
    "regime_confidence",
    "trend_up_age_bars",
)


@dataclass(frozen=True)
class DistributionStats:
    count: int
    minimum: Decimal | None
    p10: Decimal | None
    p25: Decimal | None
    median: Decimal | None
    p75: Decimal | None
    p90: Decimal | None
    maximum: Decimal | None
    mean: Decimal | None
    stddev: Decimal | None


@dataclass(frozen=True)
class GroupDistribution:
    group: str
    stats: DistributionStats


@dataclass(frozen=True)
class QuartileBucket:
    quartile: str
    lower_bound: Decimal | None
    upper_bound: Decimal | None
    trades: int
    winners: int
    trend_down_losses: int
    other: int
    winner_rate: Decimal
    trend_down_loss_rate: Decimal
    average_pnl: Decimal


@dataclass(frozen=True)
class FeatureDistribution:
    feature: str
    overall_stats: DistributionStats
    winner_stats: DistributionStats
    trend_down_loss_stats: DistributionStats
    q25: Decimal
    q50: Decimal
    q75: Decimal
    quartiles: tuple[QuartileBucket, ...]


@dataclass(frozen=True)
class EntryQualityDistributionReport:
    run_id: str
    symbol: str
    total_trades: int
    features: tuple[FeatureDistribution, ...]


def _to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def percentile(values: list[Decimal], probability: Decimal) -> Decimal | None:
    """Linear-interpolated percentile on a sorted finite Decimal sample."""
    if not values:
        return None
    if probability < 0 or probability > 1:
        raise ValueError("probability must be in [0, 1]")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = probability * Decimal(len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def distribution_stats(values: list[Decimal]) -> DistributionStats:
    if not values:
        return DistributionStats(0, None, None, None, None, None, None, None, None, None)
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values), Decimal("0")) / Decimal(len(values))
    return DistributionStats(
        count=len(values),
        minimum=min(values),
        p10=percentile(values, Decimal("0.10")),
        p25=percentile(values, Decimal("0.25")),
        median=percentile(values, Decimal("0.50")),
        p75=percentile(values, Decimal("0.75")),
        p90=percentile(values, Decimal("0.90")),
        maximum=max(values),
        mean=mean,
        stddev=variance.sqrt(),
    )


def _feature_value(record: EntryQualityRecord, feature: str) -> Decimal | None:
    return _to_decimal(getattr(record, feature))


def _rates(records: list[EntryQualityRecord]) -> tuple[int, int, int, Decimal, Decimal, Decimal]:
    total = len(records)
    winners = sum(record.outcome_group == "WINNER" for record in records)
    losses = sum(record.outcome_group == "TREND_DOWN_LOSS" for record in records)
    other = total - winners - losses
    denominator = Decimal(total) if total else Decimal("1")
    avg_pnl = (
        sum((record.realized_pnl for record in records), Decimal("0")) / Decimal(total)
        if total else Decimal("0")
    )
    return (
        winners,
        losses,
        other,
        Decimal(winners) / denominator if total else Decimal("0"),
        Decimal(losses) / denominator if total else Decimal("0"),
        avg_pnl,
    )


def analyze_feature(records: list[EntryQualityRecord], feature: str) -> FeatureDistribution:
    usable = [(record, _feature_value(record, feature)) for record in records]
    usable = [(record, value) for record, value in usable if value is not None]
    values = [value for _, value in usable]
    if not values:
        raise ValueError(f"Feature has no values: {feature}")

    q25 = percentile(values, Decimal("0.25"))
    q50 = percentile(values, Decimal("0.50"))
    q75 = percentile(values, Decimal("0.75"))
    if q25 is None or q50 is None or q75 is None:
        raise ValueError(f"Unable to calculate quartiles for {feature}")

    winners_values = [
        value for record, value in usable if record.outcome_group == "WINNER"
    ]
    losses_values = [
        value for record, value in usable if record.outcome_group == "TREND_DOWN_LOSS"
    ]

    buckets: dict[str, list[EntryQualityRecord]] = {"Q1": [], "Q2": [], "Q3": [], "Q4": []}
    for record, value in usable:
        if value <= q25:
            bucket = "Q1"
        elif value <= q50:
            bucket = "Q2"
        elif value <= q75:
            bucket = "Q3"
        else:
            bucket = "Q4"
        buckets[bucket].append(record)

    bounds = {
        "Q1": (None, q25),
        "Q2": (q25, q50),
        "Q3": (q50, q75),
        "Q4": (q75, None),
    }
    quartiles: list[QuartileBucket] = []
    for name in ("Q1", "Q2", "Q3", "Q4"):
        bucket_records = buckets[name]
        winners, losses, other, winner_rate, loss_rate, avg_pnl = _rates(bucket_records)
        lower, upper = bounds[name]
        quartiles.append(
            QuartileBucket(
                quartile=name,
                lower_bound=lower,
                upper_bound=upper,
                trades=len(bucket_records),
                winners=winners,
                trend_down_losses=losses,
                other=other,
                winner_rate=winner_rate,
                trend_down_loss_rate=loss_rate,
                average_pnl=avg_pnl,
            )
        )

    return FeatureDistribution(
        feature=feature,
        overall_stats=distribution_stats(values),
        winner_stats=distribution_stats(winners_values),
        trend_down_loss_stats=distribution_stats(losses_values),
        q25=q25,
        q50=q50,
        q75=q75,
        quartiles=tuple(quartiles),
    )


def build_distribution_report(report: EntryQualityReport) -> EntryQualityDistributionReport:
    records = list(report.records)
    return EntryQualityDistributionReport(
        run_id=str(report.run_id),
        symbol=report.symbol,
        total_trades=len(records),
        features=tuple(analyze_feature(records, feature) for feature in FEATURES),
    )
