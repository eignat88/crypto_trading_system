from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.backtest.backtest_engine import BacktestResult
from app.backtest.portfolio import Portfolio
from app.models import Fill, Order, RiskDecision, Signal
from app.reporting import breakout_retest_v1_reproduction as reproduction


def _candle(timestamp: datetime, *, symbol: str = "BTCUSDT") -> dict:
    return {
        "symbol": symbol,
        "open_time": timestamp,
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
        "indicators": {},
    }


def _result() -> BacktestResult:
    portfolio = Portfolio(Decimal("500"))
    signal = Signal(
        action="open_long",
        symbol="BTCUSDT",
        price=Decimal("100"),
        quantity=Decimal("1"),
        timestamp=datetime(2025, 1, 1, tzinfo=timezone.utc),
        reason="test",
        strategy="BreakoutRetest",
        parameters_version="breakout_retest_v1",
    )
    order = Order(
        order_id="order-1",
        signal=signal,
        side="buy",
        quantity=Decimal("1"),
        requested_price=Decimal("100"),
        created_at=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
    )
    risk = RiskDecision(
        order_id="order-1",
        approved=True,
        risk_level="LOW",
        codes=("APPROVED",),
        reasons=("ok",),
        requested_quantity=Decimal("1"),
        approved_quantity=Decimal("1"),
    )
    fill = Fill(
        fill_id="fill-1",
        order_id="order-1",
        symbol="BTCUSDT",
        side="buy",
        quantity=Decimal("1"),
        price=Decimal("100.1"),
        commission=Decimal("0.1"),
        timestamp=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
    )
    return BacktestResult(
        portfolio=portfolio,
        total_trades=1,
        winning_trades=1,
        total_pnl=Decimal("1.25"),
        max_drawdown=Decimal("0.01"),
        signals=[signal],
        risk_decisions=[risk],
        orders=[order],
        fills=[fill],
    )


def _symbol_result(
    symbol: str,
    *,
    trades: int,
    pnl: Decimal,
    deterministic: bool = True,
    expected_match: bool = True,
) -> reproduction.SymbolReproduction:
    return reproduction.SymbolReproduction(
        symbol=symbol,
        parameters_version="breakout_retest_v1",
        total_trades=trades,
        total_pnl=pnl,
        profitable_windows=0,
        windows=(),
        deterministic=deterministic,
        expected_metrics_match=expected_match,
    )


def test_frozen_protocol_constants_match_research_control() -> None:
    assert reproduction.FROZEN_START == datetime(2024, 8, 10, tzinfo=timezone.utc)
    assert reproduction.FROZEN_END == datetime(2026, 8, 10, tzinfo=timezone.utc)
    assert reproduction.FROZEN_INTERVAL == "1h"
    assert reproduction.FROZEN_INITIAL_BALANCE == Decimal("500")
    assert reproduction.FROZEN_SEED == 42
    assert reproduction.EXPECTED_COMBINED_TRADES == 113
    assert reproduction.EXPECTED_COMBINED_PNL == Decimal(
        "-3.292723244335812425394979376"
    )


def test_production_reproduction_module_imports_v1_not_v2() -> None:
    source = inspect.getsource(reproduction)
    assert "from app.strategies.breakout_retest import" in source
    assert "breakout_retest_v2" not in source
    assert "BreakoutRetestV2" not in source


def test_validate_frozen_candles_rejects_after_frozen_end() -> None:
    candles = [_candle(reproduction.FROZEN_END)]
    with pytest.raises(ValueError, match="outside frozen reproduction range"):
        reproduction.validate_frozen_candles(candles, "BTCUSDT")


def test_validate_frozen_candles_rejects_foreign_symbol() -> None:
    candles = [_candle(reproduction.FROZEN_START, symbol="ETHUSDT")]
    with pytest.raises(ValueError, match="Unexpected symbol"):
        reproduction.validate_frozen_candles(candles, "BTCUSDT")


def test_validate_frozen_candles_rejects_non_increasing_time() -> None:
    timestamp = reproduction.FROZEN_START + timedelta(hours=1)
    candles = [_candle(timestamp), _candle(timestamp)]
    with pytest.raises(ValueError, match="strictly increasing"):
        reproduction.validate_frozen_candles(candles, "BTCUSDT")


def test_audit_fingerprint_is_deterministic_and_sensitive_to_audit_trail() -> None:
    first = _result()
    second = _result()
    assert reproduction.audit_fingerprint(first) == reproduction.audit_fingerprint(second)

    changed_signal = replace(first.signals[0], reason="different")
    changed = replace(first, signals=[changed_signal])
    assert reproduction.audit_fingerprint(first) != reproduction.audit_fingerprint(changed)


def test_build_gate_result_passes_only_exact_frozen_metrics() -> None:
    btc = _symbol_result(
        "BTCUSDT",
        trades=49,
        pnl=Decimal("-0.1391016840064235879634907285"),
    )
    eth = _symbol_result(
        "ETHUSDT",
        trades=64,
        pnl=Decimal("-3.153621560329388837431488648"),
    )
    result = reproduction.build_gate_result([btc, eth])
    assert result.combined_trades == 113
    assert result.combined_pnl == reproduction.EXPECTED_COMBINED_PNL
    assert result.deterministic is True
    assert result.combined_expected_match is True
    assert result.passed is True
    reproduction.assert_gate_passed(result)


def test_gate_fails_closed_on_symbol_or_determinism_mismatch() -> None:
    btc = _symbol_result(
        "BTCUSDT",
        trades=49,
        pnl=Decimal("-0.1391016840064235879634907285"),
        deterministic=False,
    )
    eth = _symbol_result(
        "ETHUSDT",
        trades=63,
        pnl=Decimal("-3.153621560329388837431488648"),
        expected_match=False,
    )
    result = reproduction.build_gate_result([btc, eth])
    assert result.passed is False
    with pytest.raises(RuntimeError, match="reproduction gate failed"):
        reproduction.assert_gate_passed(result)
