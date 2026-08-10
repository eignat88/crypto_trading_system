# Breakout Retest v1 — frozen strategy specification

Status: DESIGN FROZEN, NOT IMPLEMENTED, NOT BACKTESTED

Parameters version: `breakout_retest_v1`

## 1. Purpose

`Breakout Retest v1` is the second active MVP strategy candidate and is intentionally architecturally different from `TrendDCA v1`.

Hypothesis: instead of entering during an RSI pullback inside an existing trend, wait for an explicit market-structure event: price closes above recent resistance, later retests that broken level, and closes back at or above it. A long entry is allowed only after this retest-hold event.

Rejected experiments (`Trend Pullback Confirmation`, EMA200 p75, TREND_DOWN confirm3) remain in the repository for audit/reproducibility but are not active MVP strategy candidates.

This hypothesis and all first-iteration parameters are frozen before implementation and first OOS evaluation. No parameter sweep is permitted in the first evaluation.

## 2. Market and scope

- Spot only.
- Symbols: BTCUSDT and ETHUSDT.
- Timeframe: 1h.
- Long only.
- Quote currency: USDT/USDC.
- No leverage, margin or futures.
- Strategy creates signals only. Exchange access/order submission remain outside the strategy.
- Maximum two active MVP strategies: `TrendDCA v1` and `Breakout Retest v1`.

## 3. Core market idea

The strategy operates on three structural stages:

1. identify a recent resistance level using only completed historical candles;
2. require a candle to close above that resistance (`BREAKOUT`);
3. require a later candle to retest the broken level and close back at or above it (`RETEST_HOLD`).

Only after `RETEST_HOLD` is a BUY signal emitted. Execution remains next-candle-open through the existing engine.

The strategy does not use RSI as an entry trigger.

## 4. Frozen first-iteration parameters

- `resistance_lookback_bars = 20` completed candles;
- `retest_timeout_bars = 24` candles after breakout;
- base position sizing: same as `TrendDCA v1` initial order (2.5% capital target before Risk Engine adjustments);
- stop-loss: 15%;
- take-profit: 5%;
- trailing activation: 3%;
- trailing distance: 2%;
- max holding: 100 candles;
- DCA: disabled for Breakout Retest v1;
- random seed for backtest: 42.

`20` bars represent a local structural resistance window on 1h data. `24` bars represent one trading day for retest opportunity. These are design assumptions, not values selected from observed OOS PnL. They must not be changed after the first OOS result is observed.

## 5. Required inputs

Required candle fields:

- open_time;
- open;
- high;
- low;
- close;
- symbol.

Required indicators/context:

- EMA50;
- EMA200;
- market regime;
- volatility20 (optional; absent is allowed).

RSI is not required by the entry state machine.

The strategy must use only current and past completed-candle information.

## 6. Resistance calculation

For candle index `N`, resistance is:

`max(high[N-20 : N])`

The current candle `N` is explicitly excluded.

Requirements:

- exactly the 20 immediately preceding completed candles are used;
- if fewer than 20 completed prior candles exist, no breakout may be detected;
- the resistance calculation must never include current or future candle high/close values;
- resistance must be calculated independently for each symbol.

## 7. Context filter

A breakout setup can be created only if all conditions hold at the breakout candle close:

1. no open position;
2. enough prior candles exist for the 20-bar resistance;
3. `close > EMA200`;
4. `EMA50 > EMA200`;
5. `regime != TREND_DOWN`;
6. volatility is absent or `<= 0.8`.

The context filter is deliberately weaker than requiring `TREND_UP`: a structural breakout can occur while the regime detector still labels the market `RANGE`.

No BUY signal is emitted solely because these conditions are true.

## 8. Breakout definition

A breakout occurs when, on candle close:

- all context conditions in section 7 hold;
- current `close > resistance_level` where `resistance_level` uses only the prior 20 completed candles.

On breakout, transition from `IDLE` to `BREAKOUT_ARMED` and persist:

- `breakout_time`;
- `breakout_level`;
- `breakout_close`;
- `breakout_ema50`;
- `breakout_ema200`;
- `breakout_regime`;
- `bars_since_breakout = 0`.

No BUY signal is emitted on the breakout candle.

A breakout candle cannot also be its own retest candle.

## 9. State machine

Per-symbol states:

- `IDLE`;
- `BREAKOUT_ARMED`.

State must be instance-local, serializable and restart-safe. No global mutable state.

### 9.1 IDLE -> BREAKOUT_ARMED

Transition only on the breakout conditions from sections 7-8.

### 9.2 BREAKOUT_ARMED -> RETEST_HOLD -> BUY SIGNAL

Retest may be evaluated only on a later completed candle.

A valid retest-hold requires all of:

1. no open position;
2. `bars_since_breakout < 24` after increment/evaluation according to section 10;
3. current `low <= breakout_level`;
4. current `close >= breakout_level`;
5. current `close > EMA200`;
6. current `EMA50 > EMA200`;
7. current `regime != TREND_DOWN`;
8. volatility absent or `<= 0.8`.

This definition intentionally has no ATR tolerance and no percent buffer in v1. The first test evaluates the simplest unambiguous structural retest: price touches/pierces the broken level intrabar and closes back at/above it.

If valid, emit one long signal on the retest candle close.

Signal reason: `Breakout retest held`.

Signal metadata must include at minimum:

- `breakout_time`;
- `retest_time`;
- `breakout_level`;
- `breakout_close`;
- `retest_low`;
- `retest_close`;
- `bars_since_breakout`;
- `resistance_lookback_bars`;
- `retest_timeout_bars`.

After signal emission, clear the breakout setup. Position state changes only through `on_fill`, not at signal generation.

Execution is only at next candle open through the existing backtest/execution pipeline.

## 10. Retest timeout semantics

Frozen timeout: `24` completed candles after breakout.

On each later candle while `BREAKOUT_ARMED`:

1. increment `bars_since_breakout`;
2. evaluate invalidation/context rules;
3. if `bars_since_breakout >= 24`, cancel before accepting a retest on that candle;
4. otherwise evaluate `RETEST_HOLD`.

Therefore a retest occurring on the 24th completed candle after breakout is too late and must not generate a signal.

Repeated candles above breakout level do not reset the timeout.

A new higher local resistance appearing while already armed does not replace/reset the stored breakout level in v1.

## 11. Setup cancellation

While `BREAKOUT_ARMED`, cancel immediately before retest confirmation if any condition holds:

1. open position appears;
2. `regime == TREND_DOWN`;
3. `close <= EMA200`;
4. `EMA50 <= EMA200`;
5. timeout reaches 24 bars.

The stored setup is cleared and state returns to `IDLE`.

Cancellation emits no order.

After cancellation, a new breakout may be armed only by a subsequent candle satisfying a fresh breakout against its own prior-20-bar resistance.

## 12. No DCA in Breakout Retest v1

DCA is explicitly disabled.

Rationale: a failed breakout/retest is a structural invalidation risk. Averaging down would mix the breakout hypothesis with mean-reversion behavior and make attribution ambiguous.

The engine may support DCA generally, but this strategy must not emit DCA add signals in v1.

## 13. Position sizing and Risk Engine

Initial target size remains aligned with the existing MVP baseline:

- maximum position allocation: 10% of capital;
- base order target: 25% of that maximum;
- initial target therefore 2.5% of current capital before Risk Engine adjustments.

Risk Engine remains authoritative and may reject/reduce/block the order according to existing limits.

No strategy rule may bypass:

- free-capital checks;
- asset exposure;
- total utilization;
- daily/weekly loss limits;
- max drawdown;
- data freshness;
- API/PostgreSQL health;
- reconciliation state;
- emergency stop.

## 14. Exit behavior for first controlled evaluation

To isolate the new entry idea while avoiding new exit optimization, first-iteration exits remain identical to the current baseline engine/TrendDCA exit model except DCA is disabled:

- stop-loss 15%;
- take-profit 5%;
- trailing activation 3%;
- trailing distance 2%;
- max holding 100 candles;
- exit on `TREND_DOWN`;
- intrabar stop/TP semantics remain engine-owned and unchanged;
- end-of-backtest liquidation remains unchanged.

Changing exits in the first Breakout Retest result is prohibited.

## 15. Causality requirements

- resistance excludes the current candle;
- breakout uses only prior resistance plus the just-closed breakout candle;
- retest occurs only on a later candle;
- signal is generated only after retest candle close;
- signal executes at N+1 open;
- final-candle signal without N+1 remains unfilled;
- no future high/low/close/EMA/regime may affect resistance, breakout or retest;
- state must not mutate position/DCA state before an actual fill;
- backtest must be deterministic for fixed seed/data/config.

## 16. Required audit fields

Every base entry signal must persist enough information to reproduce the setup:

- strategy = `breakout_retest`;
- parameters_version = `breakout_retest_v1`;
- symbol;
- signal time;
- breakout time;
- breakout level;
- breakout close;
- retest time;
- retest low/close;
- EMA50/EMA200 at retest;
- regime at retest;
- bars since breakout;
- quantity;
- reason;
- indicator/context snapshot.

Backtest artifacts must still retain signals, risk decisions, orders, fills and final metrics through the existing audit pipeline.

## 17. Unit-test acceptance criteria

Implementation is not ready until tests cover at least:

1. resistance uses exactly prior 20 highs and excludes current candle;
2. fewer than 20 prior candles cannot arm breakout;
3. close equal to resistance is not a breakout;
4. close above resistance arms setup but emits no BUY;
5. breakout candle cannot self-retest;
6. later candle with `low <= level` and `close >= level` confirms retest;
7. low never reaching level does not confirm;
8. low reaches level but close below level does not confirm;
9. `TREND_DOWN` cancels armed breakout;
10. close at/below EMA200 cancels;
11. EMA50 at/below EMA200 cancels;
12. timeout at 24 bars cancels before confirmation;
13. repeated candles do not reset timeout or breakout level;
14. signal clears setup but does not mark a position before fill;
15. no DCA signal can be emitted;
16. exit behavior matches frozen baseline exit rules for equivalent position state;
17. final-candle retest may create signal but cannot create fill;
18. two independent strategy instances do not share state;
19. BTC and ETH symbol states are independent in the same instance;
20. deterministic repeated backtest with same seed produces identical result.

## 18. First backtest protocol

Use the exact established historical dataset/protocol:

- range: `2024-08-10T00:00:00Z` to `2026-08-10T00:00:00Z`;
- interval: 1h;
- symbols: BTCUSDT and ETHUSDT;
- initial balance: 500 USDT per independent test;
- seed: 42;
- same commission/slippage model;
- same Risk Engine;
- walk-forward: train 180d / test 60d / step 60d;
- same 9 complete OOS windows per symbol;
- no TRAIN optimization in v1.

TRAIN exists for chronology/warmup only. It must not tune lookback, timeout, exits or context filters.

## 19. Comparators

Primary engineering comparator: `TrendDCA v1` fixed walk-forward baseline.

Known baseline reproducibility gate:

- BTC OOS PnL: `-1.919472385900019863816920150`, 54 trades;
- ETH OOS PnL: `-3.468563029505904349952368764`, 66 trades;
- combined OOS PnL: `-5.388035415405924213769288914`;
- combined trades: 120;
- profitable windows: 7/18.

The rejected `Trend Pullback Confirmation v1` may be shown as a secondary reference but must not become a tuning target.

If baseline gate does not reproduce, stop and diagnose before interpreting Breakout Retest.

## 20. Pre-specified acceptance criteria

Breakout Retest v1 is considered promising only if all of the following hold:

1. BTC OOS PnL > BTC TrendDCA baseline;
2. ETH OOS PnL > ETH TrendDCA baseline;
3. combined OOS PnL > `-5.388035415405924213769288914`;
4. profitable OOS windows >= 7/18;
5. maximum OOS window drawdown does not materially worsen versus baseline;
6. result is not driven by a single exceptional window;
7. at least 30 combined closed OOS trades exist for basic interpretation;
8. at least 10 OOS trades exist for each symbol;
9. no causality, reconciliation or unit-test failure.

Because this is a structurally different and naturally less-frequent setup, the previous `>=50% baseline trade retention` rule is not appropriate. Instead, fixed absolute minimum sample gates are defined before first result: >=30 combined and >=10 per symbol.

Passing these gates still does not authorize paper/live trading automatically. A separate review decision is required.

## 21. First-result decision rules

After observing the first OOS result:

- do not sweep `lookback=10/15/20/30/50`;
- do not sweep `timeout=6/12/24/48`;
- do not add ATR breakout buffers based on the result;
- do not loosen/tighten retest conditions based on profitable windows;
- do not optimize EMA filters separately for BTC and ETH;
- do not introduce DCA to rescue poor trades;
- do not change exits to manufacture positive PnL.

If the strategy fails, first perform attribution/funnel diagnostics. Any subsequent version requires a separately named pre-specified hypothesis justified by mechanism rather than by the best observed OOS parameter.

## 22. Expected implementation target

Next implementation step should add, without modifying `TrendDCA v1`:

- `app/strategies/breakout_retest.py`;
- `tests/unit/test_breakout_retest.py`;
- `scripts/compare_breakout_retest.py`;

The existing walk-forward engine, Risk Engine, execution model, commission/slippage and audit pipeline should be reused.

No exchange integration changes are required.
