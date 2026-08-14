from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.connection import async_session_factory

QUANTITY_RECONCILIATION_TOLERANCE = Decimal("1E-17")


@dataclass(frozen=True)
class ClosedTrade:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_regime: str
    exit_reason: str
    quantity: Decimal
    entry_price: Decimal
    exit_price: Decimal
    entry_commission: Decimal
    exit_commission: Decimal
    pnl: Decimal


@dataclass(frozen=True)
class AttributionBucket:
    key: str
    trades: int
    wins: int
    losses: int
    pnl: Decimal
    gross_profit: Decimal
    gross_loss: Decimal

    @property
    def win_rate(self) -> Decimal:
        return Decimal(self.wins) / Decimal(self.trades) if self.trades else Decimal("0")

    @property
    def profit_factor(self) -> Decimal:
        if self.gross_loss == 0:
            return Decimal("0") if self.gross_profit == 0 else Decimal("Infinity")
        return self.gross_profit / abs(self.gross_loss)


@dataclass(frozen=True)
class BacktestAttribution:
    run_id: UUID
    symbol: str
    total_pnl: Decimal
    attributed_pnl: Decimal
    reconciliation_delta: Decimal
    total_trades: int
    trades: tuple[ClosedTrade, ...]
    by_month: tuple[AttributionBucket, ...]
    by_entry_regime: tuple[AttributionBucket, ...]
    by_exit_reason: tuple[AttributionBucket, ...]


@dataclass
class _OpenPosition:
    quantity: Decimal
    entry_price: Decimal
    entry_commission: Decimal
    entry_time: datetime
    entry_regime: str


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def reconstruct_closed_trades(rows: list[dict[str, Any]]) -> list[ClosedTrade]:
    """Reconstruct spot long position lifecycles from ordered fill/order audit rows.

    Persisted fill quantities use NUMERIC(38, 18), while the in-memory backtest
    can carry more Decimal precision. A tiny absolute tolerance is therefore
    allowed only when reconciling a full closing sell against the accumulated
    persisted buy quantity. Material partial/oversized sells still fail closed.
    """
    position: _OpenPosition | None = None
    trades: list[ClosedTrade] = []

    for row in rows:
        side = str(row["side"]).lower()
        quantity = _decimal(row["quantity"])
        price = _decimal(row["price"])
        commission = _decimal(row["commission"])
        fill_time = _utc(row["fill_time"])
        signal = row.get("signal") or {}
        regime = str(signal.get("regime") or "UNKNOWN")
        reason = str(signal.get("reason") or "UNKNOWN")

        if side == "buy":
            if position is None:
                position = _OpenPosition(
                    quantity=quantity,
                    entry_price=price,
                    entry_commission=commission,
                    entry_time=fill_time,
                    entry_regime=regime,
                )
                continue

            total_quantity = position.quantity + quantity
            if total_quantity <= 0:
                raise ValueError("Invalid non-positive position quantity after buy")
            position.entry_price = (
                position.entry_price * position.quantity + price * quantity
            ) / total_quantity
            position.quantity = total_quantity
            position.entry_commission += commission
            continue

        if side != "sell":
            raise ValueError(f"Unsupported fill side: {side}")
        if position is None:
            raise ValueError("Sell fill without an open spot position")

        quantity_delta = abs(quantity - position.quantity)
        if quantity_delta > QUANTITY_RECONCILIATION_TOLERANCE:
            raise ValueError(
                "Partial/oversized sell is not supported by current backtest attribution: "
                f"sell={quantity} position={position.quantity} delta={quantity_delta}"
            )

        pnl = (
            (price - position.entry_price) * position.quantity
            - position.entry_commission
            - commission
        )
        trades.append(
            ClosedTrade(
                symbol=str(row["symbol"]),
                entry_time=position.entry_time,
                exit_time=fill_time,
                entry_regime=position.entry_regime,
                exit_reason=reason,
                quantity=position.quantity,
                entry_price=position.entry_price,
                exit_price=price,
                entry_commission=position.entry_commission,
                exit_commission=commission,
                pnl=pnl,
            )
        )
        position = None

    if position is not None:
        raise ValueError("Audit contains an open position without a closing fill")

    return trades


def _bucket(trades: list[ClosedTrade], key_fn) -> tuple[AttributionBucket, ...]:
    grouped: dict[str, list[ClosedTrade]] = {}
    for trade in trades:
        grouped.setdefault(str(key_fn(trade)), []).append(trade)

    result: list[AttributionBucket] = []
    for key in sorted(grouped):
        group = grouped[key]
        wins = [trade.pnl for trade in group if trade.pnl > 0]
        losses = [trade.pnl for trade in group if trade.pnl < 0]
        result.append(
            AttributionBucket(
                key=key,
                trades=len(group),
                wins=len(wins),
                losses=len(losses),
                pnl=sum((trade.pnl for trade in group), Decimal("0")),
                gross_profit=sum(wins, Decimal("0")),
                gross_loss=sum(losses, Decimal("0")),
            )
        )
    return tuple(result)


async def build_backtest_attribution(
    run_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    reconciliation_tolerance: Decimal = Decimal("0.000000001"),
) -> BacktestAttribution:
    async with session_factory() as session:
        run_result = await session.execute(
            text(
                """
                SELECT run_id, symbol, total_pnl, total_trades
                FROM mart.backtest_run
                WHERE run_id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        run = run_result.mappings().one_or_none()
        if run is None:
            raise ValueError(f"Backtest run not found: {run_id}")

        fill_result = await session.execute(
            text(
                """
                SELECT
                    f.sequence_no,
                    f.symbol,
                    f.side,
                    f.quantity,
                    f.price,
                    f.commission,
                    f.fill_time,
                    o.payload -> 'signal' AS signal
                FROM mart.backtest_fill f
                JOIN mart.backtest_order o
                  ON o.run_id = f.run_id
                 AND o.order_id = f.order_id
                WHERE f.run_id = :run_id
                ORDER BY f.sequence_no
                """
            ),
            {"run_id": run_id},
        )
        rows = [dict(row) for row in fill_result.mappings().all()]

    trades = reconstruct_closed_trades(rows)
    attributed_pnl = sum((trade.pnl for trade in trades), Decimal("0"))
    total_pnl = _decimal(run["total_pnl"])
    delta = attributed_pnl - total_pnl

    if len(trades) != int(run["total_trades"]):
        raise ValueError(
            f"Trade count reconciliation failed for {run_id}: "
            f"attributed={len(trades)} persisted={run['total_trades']}"
        )
    if abs(delta) > reconciliation_tolerance:
        raise ValueError(
            f"PnL reconciliation failed for {run_id}: "
            f"attributed={attributed_pnl} persisted={total_pnl} delta={delta}"
        )

    return BacktestAttribution(
        run_id=run_id,
        symbol=str(run["symbol"]),
        total_pnl=total_pnl,
        attributed_pnl=attributed_pnl,
        reconciliation_delta=delta,
        total_trades=int(run["total_trades"]),
        trades=tuple(trades),
        by_month=_bucket(trades, lambda trade: trade.exit_time.strftime("%Y-%m")),
        by_entry_regime=_bucket(trades, lambda trade: trade.entry_regime),
        by_exit_reason=_bucket(trades, lambda trade: trade.exit_reason),
    )
