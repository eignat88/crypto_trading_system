from pathlib import Path
import csv


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures"
    / "tradingview"
    / "cts_v23_btcusdt_1h.csv"
)


EXPECTED_DCA_TIME = "1786269600"


def test_cts_v23_tradingview_fixture_contains_reference_dca_signal() -> None:
    """Validate the TradingView reference point used for CTS parity tests.

    This is intentionally a fixture contract test. The next parity step will
    connect the existing CTS signal calculation pipeline and compare generated
    signals against this reference event.
    """
    with FIXTURE.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    signals = [
        row
        for row in rows
        if row["TV_DCA_SIGNAL"] == "1"
    ]

    assert len(signals) == 1

    signal = signals[0]
    assert signal["time"] == EXPECTED_DCA_TIME
    assert signal["TV_PULLBACK_STATE"] == "2"
    assert signal["TV_COOLDOWN_READY"] == "1"
