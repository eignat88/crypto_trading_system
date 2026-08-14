from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.collectors.indicator_batch_collector import _target_indices
from app.reporting.holdout_validation import HoldoutDefinition
from scripts import update_holdout_data


def _definition() -> HoldoutDefinition:
    return HoldoutDefinition(
        validation_id="test_holdout",
        purpose="test",
        strategy_name="BreakoutRetest",
        parameters_version="breakout_retest_v2",
        symbols=("BTCUSDT", "ETHUSDT"),
        exchange="bybit",
        interval="1h",
        period_start=datetime(2026, 8, 10, tzinfo=UTC),
        period_end=datetime(2027, 2, 6, tzinfo=UTC),
        unlock_at=datetime(2027, 2, 6, tzinfo=UTC),
        indicator_model_version="indicators_v2_hourly_volatility",
        regime_model_version="regime_v2_hourly_volatility",
        execution_model_version="backtest_hardened_v1",
        strategy_implementation_required_for_open=True,
    )


def test_fresh_database_collects_fixed_warmup_without_checkpoint():
    definition = _definition()
    assert update_holdout_data.next_collection_start(definition, None) == (
        definition.period_start
        - timedelta(hours=update_holdout_data.DERIVED_WARMUP_BARS)
    )


def test_next_collection_start_advances_checkpoint_by_one_interval():
    definition = _definition()
    checkpoint = definition.period_start + timedelta(hours=7)
    assert update_holdout_data.next_collection_start(definition, checkpoint) == checkpoint + timedelta(
        hours=1
    )


def test_next_collection_start_never_moves_before_holdout_start():
    definition = _definition()
    checkpoint = definition.period_start - timedelta(days=10)
    assert update_holdout_data.next_collection_start(definition, checkpoint) == (
        definition.period_start
        - timedelta(hours=update_holdout_data.DERIVED_WARMUP_BARS)
    )


def test_next_collection_start_rejects_naive_checkpoint():
    definition = _definition()
    naive = datetime(2026, 8, 10, 5, 0)
    try:
        update_holdout_data.next_collection_start(definition, naive)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive checkpoint must fail closed")


def test_target_indices_select_only_missing_candle_ids():
    candles = [
        {"candle_id": 10},
        {"candle_id": 11},
        {"candle_id": 12},
        {"candle_id": 13},
    ]
    assert _target_indices(candles, {11, 13}) == [1, 3]


def test_health_gate_reuses_exact_as_of(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_run(command, check):
        captured["command"] = command
        captured["check"] = check
        return SimpleNamespace(returncode=2)

    monkeypatch.setattr(update_holdout_data.subprocess, "run", fake_run)
    as_of = datetime(2026, 8, 12, 13, 44, 29, tzinfo=UTC)
    definition = tmp_path / "holdout.json"

    code = update_holdout_data.run_health_gate(definition, as_of=as_of)

    assert code == 2
    assert captured["check"] is False
    command = captured["command"]
    assert isinstance(command, list)
    assert "health" in command
    assert "2026-08-12T13:44:29+00:00" in command


async def test_raw_to_dds_reuses_exact_as_of(monkeypatch):
    captured: list[tuple[str, dict[str, object]]] = []

    class FakeResult:
        class Mappings:
            @staticmethod
            def all():
                return []

        @staticmethod
        def mappings():
            return FakeResult.Mappings()

    class FakeTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        @staticmethod
        def begin():
            return FakeTransaction()

        @staticmethod
        async def execute(statement, params):
            captured.append((str(statement), params))
            return FakeResult()

    monkeypatch.setattr(update_holdout_data, "async_session_factory", FakeSession)
    as_of = datetime(2026, 8, 12, 13, 44, 29, tzinfo=UTC)

    await update_holdout_data.load_raw_to_dds(_definition(), as_of=as_of)

    assert len(captured) == 2
    for statement, params in captured:
        assert ":as_of" in statement
        assert "clock_timestamp()" not in statement
        assert params["as_of"] == as_of


def test_updater_does_not_import_strategy_or_backtest_engine():
    source_path = Path(update_holdout_data.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(module.startswith("app.strategies") for module in imported_modules)
    assert not any(module.startswith("app.backtest") for module in imported_modules)
