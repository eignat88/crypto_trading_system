from app.pipeline.pipeline_state import MarketReadiness


def test_readiness_requires_history_indicators_and_regime() -> None:
    readiness = MarketReadiness(required_candles=2)
    readiness.observe("BTCUSDT", {"EMA": 1, "RSI": 2, "ATR": 3}, "TREND_UP")
    assert not readiness.is_ready("BTCUSDT")
    readiness.observe("BTCUSDT", {"EMA": 1, "RSI": 2, "ATR": 3}, "TREND_UP")
    assert readiness.is_ready("BTCUSDT")
