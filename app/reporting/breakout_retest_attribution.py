from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.backtest.backtest_engine import BacktestResult

QUANTITY_TOLERANCE = Decimal("1E-17")
PNL_TOLERANCE = Decimal("1E-24")


@dataclass(frozen=True)
class BreakoutRetestTrade:
    symbol: str
    window_index: int
    breakout_time: datetime
    breakout_level: Decimal
    breakout_close: Decimal
    breakout_strength_pct: Decimal
    retest_time: datetime
    bars_to_retest: int
    retest_low: Decimal
    retest_close: Decimal
    retest_depth_pct: Decimal
    retest_close_offset_pct: Decimal
    entry_fill_time: datetime
    entry_price: Decimal
    quantity: Decimal
    entry_regime: str
    entry_ema50: Decimal | None
    entry_ema200: Decimal | None
    entry_volatility: Decimal | None
    exit_time: datetime
    exit_price: Decimal
    exit_reason: str
    entry_commission: Decimal
    exit_commission: Decimal
    realized_pnl: Decimal
    holding_bars: int

    @property
    def outcome(self) -> str:
        if self.realized_pnl > 0:
            return "WINNER"
        if self.realized_pnl < 0:
            return "LOSER"
        return "FLAT"


@dataclass(frozen=True)
class AttributionBucket:
    key: str
    trades: int
    wins: int
    losses: int
    flat: int
    pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal

    @property
    def win_rate(self) -> Decimal:
        return Decimal(self.wins) / Decimal(self.trades) if self.trades else Decimal("0")

    @property
    def profit_factor(self) -> Decimal:
        if self.gross_loss == 0:
            return Decimal("Infinity") if self.gross_profit > 0 else Decimal("0")
        return self.gross_profit / abs(self.gross_loss)


@dataclass(frozen=True)
class FeatureStats:
    feature: str
    outcome: str
    count: int
    mean: Decimal | None
    median: Decimal | None
    p25: Decimal | None
    p75: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None


@dataclass(frozen=True)
class BreakoutRetestAttribution:
    symbol: str
    total_trades: int
    total_pnl: Decimal
    trades: tuple[BreakoutRetestTrade, ...]
    by_exit_reason: tuple[AttributionBucket, ...]
    by_entry_regime: tuple[AttributionBucket, ...]
    by_window: tuple[AttributionBucket, ...]
    by_outcome: tuple[AttributionBucket, ...]
    feature_stats: tuple[FeatureStats, ...]


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else _decimal(value)


def _datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"Expected datetime, got {type(value)!r}")
    return value


def _metadata_decimal(metadata: dict[str, Any], key: str) -> Decimal:
    if key not in metadata:
        raise ValueError(f"Breakout entry metadata missing {key}")
    return _decimal(metadata[key])


def _metadata_datetime(metadata: dict[str, Any], key: str) -> datetime:
    value = metadata.get(key)
    if not isinstance(value, str):
        raise ValueError(f"Breakout entry metadata missing datetime {key}")
    return datetime.fromisoformat(value)


def reconstruct_breakout_retest_trades(
    result: BacktestResult,
    *,
    symbol: str,
    window_index: int,
) -> tuple[BreakoutRetestTrade, ...]:
    """Reconstruct closed Breakout Retest trades from the in-memory audit trail.

    Breakout Retest v1 has DCA disabled, so each lifecycle must contain exactly
    one buy fill followed by one full sell fill. Entry structure is read from the
    actual entry signal metadata; no breakout/retest condition is recalculated.
    """
    orders_by_id = {order.order_id: order for order in result.orders}
    open_entry: tuple[Any, Any] | None = None
    trades: list[BreakoutRetestTrade] = []

    for fill in result.fills:
        order = orders_by_id.get(fill.order_id)
        if order is None:
            raise ValueError(f"Fill {fill.fill_id} has no matching order {fill.order_id}")
        side = str(fill.side).lower()

        if side == "buy":
            if open_entry is not None:
                raise ValueError("Breakout Retest v1 produced multiple buy fills before close")
            if order.signal.reason != "Breakout retest held":
                raise ValueError(
                    "Unexpected Breakout Retest buy reason: " f"{order.signal.reason}"
                )
            open_entry = (fill, order.signal)
            continue

        if side != "sell":
            raise ValueError(f"Unsupported fill side: {fill.side}")
        if open_entry is None:
            raise ValueError("Sell fill without an open Breakout Retest position")

        entry_fill, entry_signal = open_entry
        if abs(_decimal(fill.quantity) - _decimal(entry_fill.quantity)) > QUANTITY_TOLERANCE:
            raise ValueError(
                "Breakout Retest close quantity mismatch: "
                f"entry={entry_fill.quantity} exit={fill.quantity}"
            )

        metadata = dict(entry_signal.metadata)
        breakout_level = _metadata_decimal(metadata, "breakout_level")
        breakout_close = _metadata_decimal(metadata, "breakout_close")
        retest_low = _metadata_decimal(metadata, "retest_low")
        retest_close = _metadata_decimal(metadata, "retest_close")
        if breakout_level <= 0:
            raise ValueError("breakout_level must be positive")

        quantity = _decimal(entry_fill.quantity)
        entry_price = _decimal(entry_fill.price)
        exit_price = _decimal(fill.price)
        entry_commission = _decimal(entry_fill.commission)
        exit_commission = _decimal(fill.commission)
        pnl = (
            (exit_price - entry_price) * quantity
            - entry_commission
            - exit_commission
        )
        entry_time = _datetime(entry_fill.timestamp)
        exit_time = _datetime(fill.timestamp)
        holding_seconds = (exit_time - entry_time).total_seconds()
        if holding_seconds < 0:
            raise ValueError("Exit precedes entry")

        indicators = dict(entry_signal.indicators or {})
        trades.append(
            BreakoutRetestTrade(
                symbol=symbol,
                window_index=window_index,
                breakout_time=_metadata_datetime(metadata, "breakout_time"),
                breakout_level=breakout_level,
                breakout_close=breakout_close,
                breakout_strength_pct=(breakout_close - breakout_level) / breakout_level,
                retest_time=_metadata_datetime(metadata, "retest_time"),
                bars_to_retest=int(metadata["bars_since_breakout"]),
                retest_low=retest_low,
                retest_close=retest_close,
                retest_depth_pct=(breakout_level - retest_low) / breakout_level,
                retest_close_offset_pct=(retest_close - breakout_level) / breakout_level,
                entry_fill_time=entry_time,
                entry_price=entry_price,
                quantity=quantity,
                entry_regime=str(entry_signal.regime or "UNKNOWN"),
                entry_ema50=_optional_decimal(indicators.get("ema_50")),
                entry_ema200=_optional_decimal(indicators.get("ema_200")),
                entry_volatility=_optional_decimal(indicators.get("volatility")),
                exit_time=exit_time,
                exit_price=exit_price,
                exit_reason=str(order.signal.reason),
                entry_commission=entry_commission,
                exit_commission=exit_commission,
                realized_pnl=pnl,
                holding_bars=int(holding_seconds // 3600),
            )
        )
        open_entry = None

    if open_entry is not None:
        raise ValueError("Backtest audit ended with an unclosed Breakout Retest position")

    attributed_pnl = sum((trade.realized_pnl for trade in trades), Decimal("0"))
    if len(trades) != result.total_trades:
        raise ValueError(
            "Breakout attribution trade reconciliation failed: "
            f"expected={result.total_trades} reconstructed={len(trades)}"
        )
    if abs(attributed_pnl - result.total_pnl) > PNL_TOLERANCE:
        raise ValueError(
            "Breakout attribution PnL reconciliation failed: "
            f"expected={result.total_pnl} reconstructed={attributed_pnl}"
        )
    return tuple(trades)


def _bucket(
    trades: tuple[BreakoutRetestTrade, ...] | list[BreakoutRetestTrade],
    key_fn: Callable[[BreakoutRetestTrade], str],
) -> tuple[AttributionBucket, ...]:
    grouped: dict[str, list[BreakoutRetestTrade]] = {}
    for trade in trades:
        grouped.setdefault(str(key_fn(trade)), []).append(trade)

    result: list[AttributionBucket] = []
    for key in sorted(grouped):
        group = grouped[key]
        wins = [trade.realized_pnl for trade in group if trade.realized_pnl > 0]
        losses = [trade.realized_pnl for trade in group if trade.realized_pnl < 0]
        flats = [trade for trade in group if trade.realized_pnl == 0]
        result.append(
            AttributionBucket(
                key=key,
                trades=len(group),
                wins=len(wins),
                losses=len(losses),
                flat=len(flats),
                pnl=sum((trade.realized_pnl for trade in group), Decimal("0")),
                gross_profit=sum(wins, Decimal("0")),
                gross_loss=sum(losses, Decimal("0")),
            )
        )
    return tuple(result)


def _percentile(values: list[Decimal], p: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = Decimal(len(ordered) - 1) * p
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def _feature_stats(
    trades: tuple[BreakoutRetestTrade, ...],
) -> tuple[FeatureStats, ...]:
    extractors: dict[str, Callable[[BreakoutRetestTrade], Decimal | None]] = {
        "breakout_strength_pct": lambda trade: trade.breakout_strength_pct,
        "bars_to_retest": lambda trade: Decimal(trade.bars_to_retest),
        "retest_depth_pct": lambda trade: trade.retest_depth_pct,
        "retest_close_offset_pct": lambda trade: trade.retest_close_offset_pct,
        "holding_bars": lambda trade: Decimal(trade.holding_bars),
        "entry_volatility": lambda trade: trade.entry_volatility,
    }
    result: list[FeatureStats] = []
    for feature, extractor in extractors.items():
        for outcome in ("WINNER", "LOSER", "FLAT", "ALL"):
            selected = trades if outcome == "ALL" else tuple(
                trade for trade in trades if trade.outcome == outcome
            )
            values = [value for trade in selected if (value := extractor(trade)) is not None]
            result.append(
                FeatureStats(
                    feature=feature,
                    outcome=outcome,
                    count=len(values),
                    mean=(sum(values, Decimal("0")) / Decimal(len(values))) if values else None,
                    median=_percentile(values, Decimal("0.5")),
                    p25=_percentile(values, Decimal("0.25")),
                    p75=_percentile(values, Decimal("0.75")),
                    minimum=min(values) if values else None,
                    maximum=max(values) if values else None,
                )
            )
    return tuple(result)


def build_breakout_retest_attribution(
    trades: tuple[BreakoutRetestTrade, ...],
    *,
    symbol: str,
) -> BreakoutRetestAttribution:
    symbol_trades = tuple(trade for trade in trades if trade.symbol == symbol)
    total_pnl = sum((trade.realized_pnl for trade in symbol_trades), Decimal("0"))
    return BreakoutRetestAttribution(
        symbol=symbol,
        total_trades=len(symbol_trades),
        total_pnl=total_pnl,
        trades=symbol_trades,
        by_exit_reason=_bucket(symbol_trades, lambda trade: trade.exit_reason),
        by_entry_regime=_bucket(symbol_trades, lambda trade: trade.entry_regime),
        by_window=_bucket(symbol_trades, lambda trade: f"w{trade.window_index:02d}"),
        by_outcome=_bucket(symbol_trades, lambda trade: trade.outcome),
        feature_stats=_feature_stats(symbol_trades),
    )
