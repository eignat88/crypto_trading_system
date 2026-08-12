# Trend Pullback Confirmation v1 — frozen strategy specification

Status: DESIGN FROZEN, NOT IMPLEMENTED, NOT BACKTESTED

Parameters version: `trend_pullback_confirmation_v1`

## 1. Purpose

This is the second and final strategy candidate for MVP. It is intentionally separate from `TrendDCA v1` and must not mutate the baseline strategy.

Hypothesis: entering immediately on `RSI <= 45` inside `TREND_UP` is too early because the pullback may still be developing. Waiting for an explicit recovery/continuation confirmation after the pullback should improve entry quality without predicting the future transition directly.

This hypothesis is fixed before implementation/backtest. No parameter sweep is permitted in the first evaluation.

## 2. Market and scope

- Spot only.
- Symbols: BTCUSDT and ETHUSDT.
- Timeframe: 1h.
- Long only.
- Quote currency: USDT/USDC.
- No leverage, margin or futures.
- Strategy produces signals only. Exchange access and order submission remain outside the strategy.

## 3. What changes versus TrendDCA v1

Only the initial base-entry state machine changes.

The following remain identical to the current TrendDCA baseline for the first controlled comparison:

- position sizing;
- maximum capital per position;
- Risk Engine checks and limits;
- DCA percentages and thresholds;
- DCA allowed only while `TREND_UP`;
- stop-loss;
- take-profit;
- trailing stop;
- max holding period;
- exit on `TREND_DOWN`;
- commission/slippage/latency behavior;
- next-candle-open execution semantics;
- deterministic random seed in backtest.

This isolates the effect of the new base-entry mechanism.

## 4. Required indicators

The strategy uses only information available at the close of the current candle:

- EMA20;
- EMA50;
- EMA200;
- RSI14;
- volatility20;
- market regime.

No future candle or future regime information is allowed.

## 5. State machine

Per symbol state:

- `IDLE`
- `PULLBACK_ARMED`

State must be instance-local and restart-serializable. No global state.

### 5.1 IDLE -> PULLBACK_ARMED

A pullback setup is armed when all conditions hold on candle close:

1. no open position;
2. `regime == TREND_UP`;
3. `close > EMA200`;
4. `EMA50 > EMA200`;
5. `RSI <= 45`;
6. volatility is absent or `<= 0.8`.

On arm, store:

- `setup_time`;
- `setup_rsi`;
- `setup_close`;
- `setup_ema20`;
- `setup_ema50`;
- `setup_ema200`;
- `setup_regime`;
- `bars_since_setup = 0`.

No BUY signal is emitted at setup time.

### 5.2 PULLBACK_ARMED -> CONFIRMED ENTRY

A base BUY signal is emitted only when all conditions hold on a later candle close:

1. no open position;
2. `regime == TREND_UP`;
3. `close > EMA200`;
4. `EMA50 > EMA200`;
5. previous candle RSI `<= 45` and current candle RSI `> 45` (strict upward cross of 45);
6. current `close > EMA20`;
7. volatility is absent or `<= 0.8`.

The signal is generated on the confirmation candle close and is eligible for execution only at the next candle open through the existing backtest/execution pipeline.

Signal reason: `Trend pullback recovery confirmed`.

Signal metadata must include at minimum:

- `setup_time`;
- `confirmation_time`;
- `setup_rsi`;
- `confirmation_rsi`;
- `bars_since_setup`;
- `confirmation_close`;
- `confirmation_ema20`;
- `confirmation_ema50`;
- `confirmation_ema200`.

After signal generation, the setup state is cleared. Strategy state must advance to a filled/open-position state only through `on_fill`, preserving the existing causal contract.

## 6. Setup cancellation

While `PULLBACK_ARMED`, cancel the setup immediately if any condition occurs before confirmation:

1. `regime != TREND_UP`;
2. `close <= EMA200`;
3. `EMA50 <= EMA200`;
4. an open position appears;
5. setup reaches 12 completed candles without confirmation.

`setup_timeout_bars = 12` is fixed before first backtest. It is a design assumption representing a short intraday pullback on the 1h timeframe, not a value selected from PnL optimization. It must not be changed after observing the first V2 OOS result.

Timeout semantics: if `bars_since_setup >= 12` at evaluation time, cancel before considering a later confirmation.

## 7. Re-arming behavior

After cancellation, the strategy returns to `IDLE`.

A new setup may be armed only from a subsequent candle satisfying the setup conditions. Cancellation and re-arm must not emit an order by themselves.

While already `PULLBACK_ARMED`, another `RSI <= 45` candle does not create a second concurrent setup and does not reset the original timeout.

## 8. Position sizing and risk

Initial position sizing is identical to TrendDCA v1:

- max position allocation: 10% of capital;
- base order: 25% of max position allocation;
- therefore initial base order target remains 2.5% of capital before Risk Engine adjustments.

Risk Engine remains authoritative. Strategy approval never bypasses capital, drawdown, staleness, reconciliation or emergency-stop checks.

## 9. DCA and exits

For the first controlled V2 comparison, inherit the existing TrendDCA behavior unchanged:

- DCA1 after 3% drop;
- DCA2 after 5% drop;
- DCA3 after 8% drop;
- DCA additions only in `TREND_UP`;
- TP 5%;
- SL 15%;
- trailing activation 3%;
- trailing distance 2%;
- max holding 100 candles;
- exit on `TREND_DOWN`.

Changing any of these during the first V2 experiment is prohibited because it would confound entry attribution.

## 10. Causality requirements

- Setup uses only current/past candle data.
- Confirmation uses previous RSI and current closed-candle values only.
- Confirmation signal executes on next candle open.
- Final-candle signal without a next candle remains unfilled.
- Intrabar stop/TP semantics remain engine-owned and unchanged.
- No future regime, high, low, close or indicator values may affect setup/confirmation.

## 11. Unit-test acceptance criteria

Implementation is not ready until tests cover at least:

1. setup arms without immediate BUY;
2. RSI upward cross + close above EMA20 confirms entry;
3. RSI still below/equal 45 does not confirm;
4. RSI above 45 without a cross does not confirm;
5. close at/below EMA20 does not confirm;
6. regime change cancels setup;
7. close at/below EMA200 cancels setup;
8. EMA50 at/below EMA200 cancels setup;
9. timeout at 12 bars cancels setup;
10. repeated setup candles do not reset timeout;
11. confirmation state clears after signal;
12. strategy state advances through fill semantics, not signal emission alone;
13. DCA and exits remain behaviorally identical to baseline for equivalent open positions;
14. final-candle confirmation does not produce a fill in causal backtest.

## 12. First backtest protocol

The first evaluation must use the exact historical dataset and cost/risk model already used by the baseline:

- range: `2024-08-10T00:00:00Z` to `2026-08-10T00:00:00Z`;
- 1h;
- BTCUSDT and ETHUSDT;
- initial balance 500 USDT per independent test;
- seed 42;
- same commission/slippage/Risk Engine;
- walk-forward: train 180d / test 60d / step 60d;
- no parameter optimization in TRAIN for V2 v1;
- same 9 complete OOS windows per symbol.

The TRAIN segment is chronology only for the first fixed-parameter V2 evaluation; it must not tune `RSI=45`, timeout=12, EMA periods or exits.

## 13. Baseline comparison

Primary comparator: existing fixed `TrendDCA v1` walk-forward baseline.

Known baseline gates that must reproduce before interpreting V2:

- BTC OOS PnL: `-1.919472385900019863816920150`, 54 trades;
- ETH OOS PnL: `-3.468563029505904349952368764`, 66 trades;
- combined OOS PnL: `-5.388035415405924213769288914`;
- combined trades: 120;
- profitable windows: 7/18.

If baseline reproduction differs, stop interpretation and diagnose first.

## 14. Pre-specified V2 evaluation criteria

V2 is not accepted for paper trading merely because total PnL improves.

For a positive engineering result, require all of the following:

1. BTC OOS PnL improves versus baseline;
2. ETH OOS PnL improves versus baseline;
3. combined OOS PnL improves versus baseline;
4. profitable OOS windows >= baseline 7/18;
5. no material deterioration of max OOS window drawdown;
6. improvement is not produced by only one window;
7. trade count remains large enough for interpretation; target retention >= 50% of baseline (>=60 combined trades);
8. no causal/reconciliation/test failure.

Even if all pass, the next stage remains review/walk-forward evidence; paper trading requires an explicit subsequent decision.

## 15. Prohibited first-iteration changes

After the first V2 result is observed, do not immediately sweep or tune:

- RSI threshold;
- timeout bars;
- EMA periods;
- confirmation level;
- requiring one/two/three confirmation candles;
- ATR/volatility thresholds;
- TP/SL/trailing/DCA values.

Any future change requires a separately named hypothesis/version and justification independent of the observed OOS optimum.

## 16. Implementation target

Expected implementation files for the next step:

- `app/strategies/trend_pullback_confirmation.py`;
- `tests/unit/test_trend_pullback_confirmation.py`;
- controlled comparison script reusing `app/backtest/walk_forward.py` and the existing baseline.

No exchange integration changes are required.
