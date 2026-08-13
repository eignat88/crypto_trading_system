from pathlib import Path

import pandas as pd
import pytest


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "tradingview"


@pytest.fixture(params=[
    "cts_v23_btcusdt_1h.csv",
    "cts_v23_ethusdt_1h.csv",
])
def tradingview_fixture(request: pytest.FixtureRequest) -> pd.DataFrame:
    path = FIXTURE_DIR / request.param
    if not path.exists():
        pytest.skip(f"TradingView fixture is not available: {path}")
    return pd.read_csv(path)


def test_fixture_has_rows(tradingview_fixture: pd.DataFrame) -> None:
    assert len(tradingview_fixture) > 0


def test_fixture_required_columns(tradingview_fixture: pd.DataFrame) -> None:
    required = {
        "TV_EMA20",
        "TV_EMA50",
        "TV_EMA200",
        "TV_RSI14",
        "TV_ATR14",
        "TV_HTF_EMA20",
        "TV_HTF_EMA50",
        "TV_HTF_EMA200",
        "TV_HTF_RSI14",
        "TV_PULLBACK_STATE",
        "TV_COOLDOWN_READY",
        "TV_DCA_SIGNAL",
    }

    assert required.issubset(set(tradingview_fixture.columns))


def test_state_values_are_valid(tradingview_fixture: pd.DataFrame) -> None:
    assert set(tradingview_fixture["TV_PULLBACK_STATE"].dropna()).issubset({0, 1, 2})


def test_signal_values_are_valid(tradingview_fixture: pd.DataFrame) -> None:
    assert set(tradingview_fixture["TV_DCA_SIGNAL"].dropna()).issubset({0, 1})


def test_cooldown_values_are_valid(tradingview_fixture: pd.DataFrame) -> None:
    assert set(tradingview_fixture["TV_COOLDOWN_READY"].dropna()).issubset({0, 1})
