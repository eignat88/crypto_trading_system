"""Tests for PaperReconciler — periodic state reconciliation between runtime and DB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.reconciliation.paper_reconciler import (
    Discrepancy,
    DiscrepancySeverity,
    PaperReconciler,
    ReconciliationResult,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeOrder:
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    status: str
    created_at: datetime


@dataclass
class FakeFill:
    fill_id: str
    order_id: str
    symbol: str
    quantity: Decimal
    price: Decimal
    executed_at: datetime


@dataclass
class FakePosition:
    symbol: str
    quantity: Decimal
    average_price: Decimal


@dataclass
class FakeRuntimeState:
    last_processed_timestamp: datetime | None = None
    last_market_sequence: int = 0
    cash_balance: Decimal = Decimal("0")


class FakeStateReader:
    def __init__(
        self,
        balance: Decimal = Decimal("100"),
        orders: dict[str, Any] | None = None,
        fills: dict[str, Any] | None = None,
        positions: dict[str, Any] | None = None,
    ) -> None:
        self._balance = balance
        self._orders = orders or {}
        self._fills = fills or {}
        self._positions = positions or {}

    @property
    def cash_balance(self) -> Decimal:
        return self._balance

    @property
    def orders(self) -> dict[str, Any]:
        return self._orders

    @property
    def fills(self) -> dict[str, Any]:
        return self._fills

    @property
    def positions(self) -> dict[str, Any]:
        return self._positions


class FakeDatabaseReader:
    def __init__(
        self,
        state: FakeRuntimeState | None = None,
        orders: list[dict[str, Any]] | None = None,
        fills: list[dict[str, Any]] | None = None,
        positions: list[Any] | None = None,
    ) -> None:
        self._state = state or FakeRuntimeState()
        self._orders = orders or []
        self._fills = fills or []
        self._positions = positions or []

    async def load_state(self) -> FakeRuntimeState:
        return self._state

    async def load_orders(self) -> list[dict[str, Any]]:
        return self._orders

    async def load_fills(self) -> list[dict[str, Any]]:
        return self._fills

    async def load_positions(self) -> list[Any]:
        return self._positions


def _db(balance: Decimal = Decimal("100"), **kwargs: Any) -> FakeDatabaseReader:
    """Helper to create a FakeDatabaseReader with matching balance."""
    return FakeDatabaseReader(state=FakeRuntimeState(cash_balance=balance), **kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestReconciliationResult:
    def test_empty_result_is_success(self) -> None:
        result = ReconciliationResult(checked_at=datetime.now(UTC))
        assert result.success is True
        assert result.has_fatal is False
        assert result.fatal_count == 0
        assert result.recoverable_count == 0

    def test_to_dict(self) -> None:
        result = ReconciliationResult(
            checked_at=datetime.now(UTC),
            orders_runtime=5,
            orders_db=4,
            balance_runtime=Decimal("100"),
            balance_db=Decimal("99.99"),
        )
        d = result.to_dict()
        assert d["orders"]["runtime"] == 5
        assert d["orders"]["db"] == 4
        assert d["balance"]["runtime"] == "100"
        assert d["success"] is True


class TestPaperReconcilerHappyPath:
    @pytest.mark.asyncio
    async def test_identical_state_no_discrepancies(self) -> None:
        now = datetime.now(UTC)
        order = FakeOrder("o1", "BTCUSDT", "buy", Decimal("0.01"), "FILLED", now)
        fill = FakeFill("f1", "o1", "BTCUSDT", Decimal("0.01"), Decimal("100"), now)
        position = FakePosition("BTCUSDT", Decimal("0.01"), Decimal("100"))

        state_reader = FakeStateReader(
            balance=Decimal("100"),
            orders={"o1": order},
            fills={"f1": fill},
            positions={"BTCUSDT": position},
        )
        db_reader = FakeDatabaseReader(
            state=FakeRuntimeState(cash_balance=Decimal("100")),
            orders=[{"order_id": "o1", "status": "FILLED"}],
            fills=[{"fill_id": "f1", "order_id": "o1"}],
            positions=[FakePosition("BTCUSDT", Decimal("0.01"), Decimal("100"))],
        )

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.success is True
        assert result.has_fatal is False
        assert len(result.discrepancies) == 0
        assert result.orders_runtime == 1
        assert result.orders_db == 1


class TestPaperReconcilerOrderDiscrepancies:
    @pytest.mark.asyncio
    async def test_order_missing_in_db_is_recoverable(self) -> None:
        now = datetime.now(UTC)
        order = FakeOrder("o1", "BTCUSDT", "buy", Decimal("0.01"), "FILLED", now)

        state_reader = FakeStateReader(orders={"o1": order})
        db_reader = _db(orders=[])

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is False
        assert result.recoverable_count == 1
        assert result.discrepancies[0].category == "order_missing_in_db"
        assert result.discrepancies[0].severity == DiscrepancySeverity.RECOVERABLE

    @pytest.mark.asyncio
    async def test_order_missing_in_runtime_is_fatal(self) -> None:
        state_reader = FakeStateReader(orders={})
        db_reader = _db(
            orders=[{"order_id": "o1", "status": "FILLED"}]
        )

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        assert result.fatal_count == 1
        assert result.discrepancies[0].category == "order_missing_in_runtime"
        assert result.discrepancies[0].severity == DiscrepancySeverity.FATAL


class TestPaperReconcilerFillDiscrepancies:
    @pytest.mark.asyncio
    async def test_fill_missing_in_db_is_recoverable(self) -> None:
        now = datetime.now(UTC)
        fill = FakeFill("f1", "o1", "BTCUSDT", Decimal("0.01"), Decimal("100"), now)

        state_reader = FakeStateReader(fills={"f1": fill})
        db_reader = _db(fills=[])

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is False
        assert result.discrepancies[0].category == "fill_missing_in_db"

    @pytest.mark.asyncio
    async def test_fill_missing_in_runtime_is_fatal(self) -> None:
        state_reader = FakeStateReader(fills={})
        db_reader = _db(
            fills=[{"fill_id": "f1", "order_id": "o1"}]
        )

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        assert result.discrepancies[0].category == "fill_missing_in_runtime"


class TestPaperReconcilerPositionDiscrepancies:
    @pytest.mark.asyncio
    async def test_position_missing_in_db_with_quantity_is_fatal(self) -> None:
        position = FakePosition("BTCUSDT", Decimal("0.01"), Decimal("100"))
        state_reader = FakeStateReader(positions={"BTCUSDT": position})
        db_reader = _db(positions=[])

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        assert result.discrepancies[0].category == "position_missing_in_db"

    @pytest.mark.asyncio
    async def test_position_missing_in_db_with_zero_qty_is_ok(self) -> None:
        position = FakePosition("BTCUSDT", Decimal("0"), Decimal("100"))
        state_reader = FakeStateReader(positions={"BTCUSDT": position})
        db_reader = _db(positions=[])

        reconciler = PaperReconciler(
            state_reader=state_reader, db_reader=db_reader,
            position_tolerance=Decimal("0.00000001"),
        )
        result = await reconciler.reconcile()

        assert result.has_fatal is False

    @pytest.mark.asyncio
    async def test_position_quantity_mismatch_is_fatal(self) -> None:
        rt_pos = FakePosition("BTCUSDT", Decimal("0.01"), Decimal("100"))
        db_pos = FakePosition("BTCUSDT", Decimal("0.02"), Decimal("100"))
        state_reader = FakeStateReader(positions={"BTCUSDT": rt_pos})
        db_reader = _db(positions=[db_pos])

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        assert result.discrepancies[0].category == "position_quantity_mismatch"


class TestPaperReconcilerBalance:
    @pytest.mark.asyncio
    async def test_balance_match_is_ok(self) -> None:
        state_reader = FakeStateReader(balance=Decimal("100"))
        db_reader = FakeDatabaseReader(state=FakeRuntimeState(cash_balance=Decimal("100")))

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)
        result = await reconciler.reconcile()

        assert result.has_fatal is False

    @pytest.mark.asyncio
    async def test_balance_within_tolerance_is_ok(self) -> None:
        state_reader = FakeStateReader(balance=Decimal("100.005"))
        db_reader = FakeDatabaseReader(state=FakeRuntimeState(cash_balance=Decimal("100")))

        reconciler = PaperReconciler(
            state_reader=state_reader, db_reader=db_reader,
            balance_tolerance=Decimal("0.01"),
        )
        result = await reconciler.reconcile()

        assert result.has_fatal is False

    @pytest.mark.asyncio
    async def test_balance_beyond_tolerance_is_fatal(self) -> None:
        state_reader = FakeStateReader(balance=Decimal("100.05"))
        db_reader = FakeDatabaseReader(state=FakeRuntimeState(cash_balance=Decimal("100")))

        reconciler = PaperReconciler(
            state_reader=state_reader, db_reader=db_reader,
            balance_tolerance=Decimal("0.01"),
        )
        result = await reconciler.reconcile()

        assert result.has_fatal is True
        assert result.discrepancies[0].category == "balance_mismatch"


class TestPaperReconcilerTracking:
    @pytest.mark.asyncio
    async def test_consecutive_fatal_tracking(self) -> None:
        state_reader = FakeStateReader(orders={})
        db_reader = FakeDatabaseReader(
            orders=[{"order_id": "o1", "status": "FILLED"}]
        )

        reconciler = PaperReconciler(state_reader=state_reader, db_reader=db_reader)

        await reconciler.reconcile()
        assert reconciler.consecutive_fatal == 1

        await reconciler.reconcile()
        assert reconciler.consecutive_fatal == 2

    @pytest.mark.asyncio
    async def test_consecutive_fatal_resets_on_success(self) -> None:
        # First: fatal
        state_reader_bad = FakeStateReader(orders={})
        db_reader_bad = _db(
            orders=[{"order_id": "o1", "status": "FILLED"}]
        )
        reconciler = PaperReconciler(
            state_reader=state_reader_bad, db_reader=db_reader_bad
        )
        await reconciler.reconcile()
        assert reconciler.consecutive_fatal == 1

        # Then: good (swap readers to matching state)
        reconciler.state_reader = FakeStateReader()
        reconciler.db_reader = _db()
        await reconciler.reconcile()
        assert reconciler.consecutive_fatal == 0

    @pytest.mark.asyncio
    async def test_callback_is_called(self) -> None:
        called_with: list[ReconciliationResult] = []

        def on_reconciled(result: ReconciliationResult) -> None:
            called_with.append(result)

        state_reader = FakeStateReader()
        db_reader = FakeDatabaseReader()

        reconciler = PaperReconciler(
            state_reader=state_reader, db_reader=db_reader,
            on_reconciled=on_reconciled,
        )
        await reconciler.reconcile()

        assert len(called_with) == 1
        assert called_with[0].success is True


class TestPaperReconcilerMissingReader:
    @pytest.mark.asyncio
    async def test_no_readers_returns_failure(self) -> None:
        reconciler = PaperReconciler()
        result = await reconciler.reconcile()
        assert result.success is False
