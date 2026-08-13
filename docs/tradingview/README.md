# TradingView CTS MVP v2.3 reference

This directory contains the Pine Script reference used to validate the isolated
Python implementation in `app/strategies/cts_trend_dca_v23.py`.

## Scope

The reference is the user-validated TradingView indicator **Crypto Trading System
MVP v2.3** for Bybit Spot BTCUSDT/ETHUSDT with:

- chart timeframe: 1H;
- higher timeframe: 4H;
- EMA 20/50/200;
- RSI 14;
- ATR 14;
- pullback RSI 40-50;
- RSI recovery +0.5;
- pullback distance 0.35 ATR;
- reset distance 0.50 ATR;
- minimum DCA interval 24 bars;
- state machine WAIT_PULLBACK -> IN_PULLBACK -> LOCKED;
- candidate generation only on confirmed chart bars.

The Pine script is a **reference signal specification**, not an execution engine.
It must not submit exchange orders or bypass Risk Engine.

## Isolation rule

This parity work must not modify the existing `TrendDCAStrategy`, Risk Engine,
Execution Engine, paper/live modes, or sealed holdout results.

The Python module intentionally does not inherit from `BaseStrategy` yet. It
returns a deterministic decision/state object only. Integration with the existing
Backtest Engine belongs to a separate PR after parity is established.

## Test coverage

`tests/unit/test_cts_tradingview_v23_parity.py` validates the Pine contract with
synthetic, deterministic indicator snapshots, including:

- BULL/BEAR/SIDEWAYS regime classification;
- previous confirmed 4H alignment matching `request.security(..., expr[1],
  lookahead=barmerge.lookahead_on)` semantics;
- pullback registration without same-bar signal emission;
- RSI recovery threshold and recovery above RSI 50;
- bullish/price confirmation;
- 24-bar cooldown;
- cooldown + reset rearm requirement;
- HTF safety reset while preserving last DCA index;
- no state mutation on a live/unconfirmed 1H bar;
- future bars not changing already produced decisions.

## Important limitation

The current unit suite is a **logic-contract parity suite**. It does not claim
numeric TradingView-vs-Python parity for EMA/RSI/ATR because no machine-readable
TradingView export of reference indicator values was supplied with the Pine file.
Existing project indicator implementations remain unchanged.

A future numeric parity fixture should be generated from TradingView without
changing CTS parameters and should contain, at minimum, timestamp, OHLC,
EMA20/50/200, RSI14, ATR14, confirmed 4H timestamp/values, pullback state,
signal and reason code. That fixture can then be added as a separate regression
without using sealed holdout performance data.
