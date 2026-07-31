import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import wraps
from typing import Any

import httpx
import pytest

import app.collectors.candle_collector as collector_module
from app.collectors.candle_collector import (
    CandleCollector,
    align_to_interval,
    interval_duration,
)
from app.exchange.base_exchange import Candle, CandleBatch
from app.exchange.bybit_client import BybitClient

START = datetime(2026, 1, 1, tzinfo=UTC)


def async_test(function: Any) -> Any:
    """Run async tests without requiring an external pytest plugin."""

    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(function(*args, **kwargs))

    return wrapper


def candle(open_time: datetime, payload: Any = None) -> Candle:
    return Candle(
        exchange_name="bybit",
        symbol="BTCUSDT",
        interval_code="5m",
        open_time=open_time,
        close_time=None,
        open_price=Decimal("1"),
        high_price=Decimal("1"),
        low_price=Decimal("1"),
        close_price=Decimal("1"),
        volume=Decimal("1"),
        quote_volume=Decimal("1"),
        trade_count=None,
        source_payload=payload,
    )


class Result:
    rowcount = 1

    def __init__(self, value: datetime | None = None) -> None:
        self.value = value

    def fetchone(self) -> tuple[datetime | None]:
        return (self.value,)


class Transaction:
    def __init__(self) -> None:
        self.rolled_back = False
        self.committed = False

    async def __aenter__(self) -> "Transaction":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None


class Session:
    def __init__(self, query_value: datetime | None = None) -> None:
        self.transaction = Transaction()
        self.calls: list[tuple[str, dict | None]] = []
        self.query_value = query_value

    async def __aenter__(self) -> "Session":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    def begin(self) -> Transaction:
        return self.transaction

    async def execute(self, statement: Any, params: dict | None = None) -> Result:
        self.calls.append((str(statement), params))
        return Result(self.query_value) if "SELECT" in str(statement) else Result()


def test_interval_duration_and_start_alignment() -> None:
    assert interval_duration("5m") == timedelta(minutes=5)
    assert interval_duration("1d") == timedelta(days=1)
    unaligned = START + timedelta(minutes=7, seconds=13)
    assert align_to_interval(unaligned, timedelta(minutes=5)) == START + timedelta(minutes=5)


@pytest.mark.parametrize(
    ("interval", "duration"),
    [
        ("5m", timedelta(minutes=5)),
        ("15m", timedelta(minutes=15)),
        ("1h", timedelta(hours=1)),
        ("4h", timedelta(hours=4)),
        ("1d", timedelta(days=1)),
    ],
)
@async_test
async def test_bybit_sets_close_time_for_every_supported_interval(
    interval: str,
    duration: timedelta,
) -> None:
    raw_row = [str(int(START.timestamp() * 1000)), "1", "2", "1", "2", "3", "6"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"retCode": 0, "result": {"list": [raw_row]}},
            request=request,
        )

    client = BybitClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url=client.BASE_URL, transport=httpx.MockTransport(handler)
    )
    try:
        batch = await client.get_candles(
            "BTCUSDT", interval, START, START + duration, limit=1
        )
    finally:
        await client.close()

    assert len(batch) == 1
    assert batch[0].open_time == START
    assert batch[0].close_time == START + duration
    assert batch[0].close_time.tzinfo is UTC


@async_test
async def test_api_candle_persists_close_time_for_raw_to_dds_boundary() -> None:
    duration = timedelta(hours=1)
    raw_row = [str(int(START.timestamp() * 1000)), "1", "2", "1", "2", "3", "6"]

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Traceid": "pilot-trace"},
            json={"retCode": 0, "result": {"list": [raw_row]}},
            request=request,
        )

    client = BybitClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url=client.BASE_URL, transport=httpx.MockTransport(handler)
    )
    session = Session()
    try:
        batch = await client.get_candles("BTCUSDT", "1h", START, START + duration, limit=1)
        inserted = await CandleCollector(client)._store_candles(session, batch)
    finally:
        await client.close()

    assert inserted == 1
    _, params = session.calls[0]
    assert params is not None
    assert params["open_time"] == START
    assert params["close_time"] == START + duration
    as_of_before_close = START + timedelta(minutes=59, seconds=59)
    as_of_at_close = START + duration
    assert params["close_time"] > as_of_before_close
    assert params["close_time"] <= as_of_at_close


@pytest.mark.parametrize("offsets", [[0, 0], [0, 10]])
def test_batch_validation_rejects_duplicates_and_gaps(offsets: list[int]) -> None:
    candles = [candle(START + timedelta(minutes=offset)) for offset in offsets]

    with pytest.raises(ValueError):
        CandleCollector._validate_batch(candles, timedelta(minutes=5), START)


def test_batch_validation_rejects_gap_at_first_page_start() -> None:
    with pytest.raises(ValueError, match="expected"):
        CandleCollector._validate_batch(
            [candle(START + timedelta(minutes=5))], timedelta(minutes=5), START
        )


@async_test
async def test_large_range_is_split_into_bounded_forward_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Exchange:
        def __init__(self) -> None:
            self.calls: list[tuple[datetime, datetime, int]] = []

        async def get_candles(self, **kwargs: Any) -> CandleBatch:
            start, end, limit = kwargs["start_time"], kwargs["end_time"], kwargs["limit"]
            self.calls.append((start, end, limit))
            values = []
            current = start
            while current <= end:
                values.append(candle(current))
                current += timedelta(minutes=5)
            return CandleBatch(list(reversed(values)))

    sessions: list[Session] = []

    def session_factory() -> Session:
        session = Session()
        sessions.append(session)
        return session

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(collector_module, "async_session_factory", session_factory)
    monkeypatch.setattr(collector_module.asyncio, "sleep", no_sleep)
    exchange = Exchange()

    loaded = await CandleCollector(exchange).load_historical_candles(
        "BTCUSDT", "5m", START, START + timedelta(minutes=30), batch_size=3
    )

    assert loaded == 6
    assert exchange.calls == [
        (START, START + timedelta(minutes=10), 3),
        (START + timedelta(minutes=15), START + timedelta(minutes=25), 3),
    ]
    assert all(session.transaction.committed for session in sessions)


@async_test
async def test_candles_at_or_after_end_are_not_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    end = START + timedelta(minutes=10)

    class Exchange:
        async def get_candles(self, **_: Any) -> CandleBatch:
            return CandleBatch(
                [
                    candle(START),
                    candle(START + timedelta(minutes=5)),
                    candle(end),
                    candle(end + timedelta(minutes=5)),
                ],
                response_payload={"result": {"list": ["original-response"]}},
            )

    session = Session()
    monkeypatch.setattr(collector_module, "async_session_factory", lambda: session)

    loaded = await CandleCollector(Exchange()).load_historical_candles(
        "BTCUSDT", "5m", START, end, batch_size=3
    )

    candle_params = [
        params
        for sql, params in session.calls
        if "INSERT INTO raw_market.candles" in sql
    ]
    assert loaded == 2
    assert [params["open_time"] for params in candle_params if params is not None] == [
        START,
        START + timedelta(minutes=5),
    ]
    assert all(
        params is not None and params["open_time"] < end
        for params in candle_params
    )
    journal_params = next(
        params
        for sql, params in session.calls
        if "INSERT INTO raw_system.loading_journal" in sql
    )
    assert journal_params is not None
    assert journal_params["end_time"] == START + timedelta(minutes=5)


@async_test
async def test_batch_provenance_and_checkpoint_roll_back_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = CandleBatch(
        [candle(START, ["raw-row"])],
        request_id="request-42",
        request_time=START,
        request_payload={"start": 1},
        response_payload={"retCode": 0, "result": {"list": [["raw-row"]]}},
    )

    class Exchange:
        async def get_candles(self, **_: Any) -> CandleBatch:
            return batch

    session = Session()
    monkeypatch.setattr(collector_module, "async_session_factory", lambda: session)
    collector = CandleCollector(Exchange())

    async def fail_api_response(*_: Any) -> None:
        raise RuntimeError("database failure")

    monkeypatch.setattr(collector, "_store_api_response", fail_api_response)
    with pytest.raises(RuntimeError, match="database failure"):
        await collector.load_historical_candles(
            "BTCUSDT", "5m", START, START + timedelta(minutes=5), batch_size=1
        )

    assert session.transaction.rolled_back
    assert not any("loading_journal" in sql for sql, _ in session.calls)


@async_test
async def test_api_response_persists_request_id_and_original_json() -> None:
    session = Session()
    batch = CandleBatch(
        [candle(START)],
        request_id="request-42",
        request_time=START,
        request_payload={"start": 1},
        response_payload={"result": {"list": [["original"]]}},
    )

    await CandleCollector(object())._store_api_response(session, batch)

    _, params = session.calls[0]
    assert params is not None
    assert params["request_id"] == "request-42"
    assert params["request_time"] == START
    assert '"original"' in params["response_payload"]


@async_test
async def test_resume_uses_maximum_successful_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    latest_boundary = START + timedelta(days=2)
    session = Session(latest_boundary)
    monkeypatch.setattr(collector_module, "async_session_factory", lambda: session)

    checkpoint = await CandleCollector(object()).get_last_checkpoint("BTCUSDT", "5m")

    assert checkpoint == latest_boundary
    assert "SELECT max(end_time)" in session.calls[0][0]


@async_test
async def test_bybit_reverse_response_is_sorted_and_retried_on_429() -> None:
    attempts = 0
    raw_rows = [
        [str(int((START + timedelta(minutes=5)).timestamp() * 1000)), "2", "3", "1", "2", "4", "8"],
        [str(int(START.timestamp() * 1000)), "1", "2", "1", "2", "3", "6"],
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(
            200,
            headers={"Traceid": "trace-123"},
            json={"retCode": 0, "result": {"list": raw_rows}},
            request=request,
        )

    client = BybitClient()
    await client.client.aclose()
    client.client = httpx.AsyncClient(
        base_url=client.BASE_URL, transport=httpx.MockTransport(handler)
    )
    try:
        batch = await client.get_candles(
            "BTCUSDT", "5m", START, START + timedelta(minutes=5), limit=2
        )
    finally:
        await client.close()

    assert attempts == 2
    assert [item.open_time for item in batch] == [START, START + timedelta(minutes=5)]
    assert batch.request_id == "trace-123"
    assert batch.response_payload["result"]["list"] == raw_rows
