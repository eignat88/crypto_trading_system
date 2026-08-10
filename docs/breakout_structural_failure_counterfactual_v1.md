# Breakout Structural Failure Counterfactual v1

Status: DESIGN FROZEN BEFORE IMPLEMENTATION

## Purpose

Test one read-only counterfactual hypothesis on the already viewed Breakout Retest v1 OOS sample. This is not a strategy change and must not be used for paper/live trading without a new independent validation stage.

## Frozen hypothesis

Evaluate exactly one structural failure condition at the close of the 24th completed hourly candle after the actual entry fill:

- close_24h < breakout_level
- close_24h < EMA20_24h
- EMA20_24h < EMA20_previous_completed_bar

All three conditions must be true.

No other conditions are permitted in v1. In particular, do not use EMA50, EMA200, PnL threshold, ATR, volatility, regime, regime confidence, RSI, symbol-specific logic, tolerance bands, or alternative horizons.

## Causal execution

The condition becomes known only after the 24h candle closes. Therefore, when all three conditions are true and the actual position is still open through the next candle open, the hypothetical SELL executes at the open of the next hourly candle (N+1), not at the 24h close.

Use:

- actual entry fill price;
- actual entry quantity;
- actual entry commission;
- N+1 open as hypothetical reference price;
- deterministic counterfactual-only sell slippage;
- taker commission on the hypothetical sell.

If N+1 is unavailable, or the actual trade exits at or before the N+1 open, the counterfactual does not trigger.

## Determinism

Counterfactual slippage must not perturb the actual backtest RNG sequence. Use an independent deterministic trade-local seed derived from the base seed, symbol, window index, and entry timestamp.

## Frozen dataset and backtest configuration

- Symbols: BTCUSDT, ETHUSDT
- Spot only
- Interval: 1h
- OOS source period: 2024-08-10T00:00:00Z to 2026-08-10T00:00:00Z
- Walk-forward: train 180d / test 60d / step 60d
- Initial balance per TEST window: 500
- Random seed: 42
- Strategy: Breakout Retest v1 (`breakout_retest_v1`)
- No parameter optimization

Expected frozen Breakout Retest reproduction before analysis:

- BTCUSDT: 49 closed OOS trades, PnL -0.1391016840064235879634907285
- ETHUSDT: 64 closed OOS trades, PnL -3.153621560329388837431488648

If reproduction fails, stop the counterfactual analysis.

## Required reporting

Report by symbol and combined:

- actual PnL;
- counterfactual PnL;
- PnL delta;
- triggered trades;
- actual winners;
- counterfactual winners;
- sacrificed winners;
- saved losers;
- saved TREND_DOWN losses;
- triggered TREND_DOWN losses;
- triggered MAX_HOLDING losses;
- per-window actual/counterfactual PnL and delta;
- per-window sacrificed winners and saved losers.

Preserve trade-level detail in a JSON artifact.

## Frozen decision gates

The hypothesis is considered technically promising only if all of the following are true:

1. BTC counterfactual PnL > actual BTC PnL.
2. ETH counterfactual PnL > actual ETH PnL.
3. Combined counterfactual PnL > actual combined PnL.
4. Combined counterfactual PnL > 0.
5. Saved TREND_DOWN losses > sacrificed winners, combined.
6. The improvement is not dependent on a single symbol.
7. The improvement is not dependent on a single OOS window; at least two windows per symbol must have positive PnL delta.
8. No causal, reconciliation, determinism, or unit-test failures.

If any gate fails, classify v1 as REJECTED. Do not tune the horizon, add/remove conditions, introduce numeric thresholds, or create symbol-specific variants on this viewed OOS sample.

## Interpretation constraint

This experiment uses an already viewed OOS sample. Even if every gate passes, the result is hypothesis-generating rather than pristine validation. It does not authorize paper or live trading. A subsequent independent validation design is required before strategy changes can be accepted.
