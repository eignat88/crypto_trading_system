# BREAKOUT RETEST v2 — INDEPENDENT VALIDATION PLAN

Status: FROZEN VALIDATION DESIGN — NO STRATEGY CHANGE

## 1. Purpose

This document freezes the independent validation plan for the next Breakout Retest research stage.

The currently viewed Breakout Retest v1 OOS sample is considered **research-exhausted**. It has already been used for:

- baseline/OOS comparison;
- entry attribution;
- exit attribution;
- post-entry path diagnostics;
- 6h/12h/24h/48h snapshots;
- naive 24h early-failure counterfactual;
- 24h structural feature snapshot;
- failed-breakout structural counterfactual;
- false-positive attribution of sacrificed winners versus saved losers.

No further parameter selection, threshold search, rule construction, symbol-specific tuning, horizon tuning, or feature selection may be justified using this sample.

The purpose of the next stage is to validate a **new strategy-management concept on independent data**, not to continue optimizing the already viewed OOS history.

## 2. Research conclusion being carried forward

The current research supports the following qualitative conclusion:

1. Failed breakouts can often be detected structurally before the existing TREND_DOWN exit.
2. A single immediate-exit decision at a fixed 24h snapshot creates material false positives.
3. Some ultimately profitable trades undergo a genuine structural breakdown before recovering.
4. Therefore, a temporary structural failure should not automatically imply an immediate exit.
5. A future strategy version may require an intermediate state representing an unresolved structural failure.

This conclusion is **hypothesis-generating only**. It is not authorization to implement or deploy a new exit rule.

## 3. Frozen conceptual hypothesis

The only concept carried into the next research cycle is:

> A breakout position that develops a structural failure may enter a temporary `FAILURE_WATCH` state instead of being closed immediately. A later causal recovery or deterioration event may resolve that state.

At this stage the following are deliberately **NOT DEFINED**:

- how many hours `FAILURE_WATCH` lasts;
- whether the state begins at 24h or another age;
- numerical PnL thresholds;
- numerical MFE or MAE thresholds;
- EMA reclaim thresholds;
- breakout-level reclaim tolerances;
- ATR/volatility thresholds;
- regime thresholds;
- symbol-specific rules;
- BTC-specific or ETH-specific variants;
- recovery timeout;
- deterioration timeout;
- any optimized parameter values.

No implementation of `FAILURE_WATCH` should begin until these design variables are frozen **before** independent validation data are inspected.

## 4. Research-exhausted dataset

The following historical period is locked for retrospective research and must not be treated as independent validation again:

- Symbols: BTCUSDT, ETHUSDT
- Venue: Bybit Spot
- Interval: 1h
- Period: `2024-08-10T00:00:00Z` to `2026-08-10T00:00:00Z`
- Walk-forward: train 180d / test 60d / step 60d
- Initial balance per test window: 500 USDT
- Random seed: 42
- Strategy: `breakout_retest_v1`

This period may still be used for:

- regression testing;
- causal bug reproduction;
- reconciliation checks;
- deterministic replay;
- documenting previously observed behavior.

It must not be used for choosing new strategy parameters.

## 5. Independent validation data policy

### 5.1 Preferred source

Use data that were not available when this plan was frozen.

Preferred validation method:

- continue collecting BTCUSDT and ETHUSDT 1h spot candles after `2026-08-10T00:00:00Z`;
- do not inspect candidate strategy performance while the validation sample is accumulating;
- open the sample only after the predefined minimum validation horizon and trade-count requirements are met.

### 5.2 Alternative historical holdout

An older historical period may be used only if all of the following are true:

- it has not previously been viewed during this project for Breakout Retest rule selection;
- its availability and completeness can be proven;
- no parameter decisions were informed by that period;
- it is explicitly recorded as a pristine holdout before the first run.

If provenance is uncertain, the period is not pristine and must not be used as independent validation.

## 6. Validation sample minimums

Before the independent validation result may be interpreted, the sample must satisfy all of the following:

- both BTCUSDT and ETHUSDT are present;
- at least 30 closed OOS-equivalent trades combined;
- at least 10 closed trades per symbol;
- at least 3 distinct non-overlapping temporal segments per symbol;
- no material candle gaps;
- no duplicate candles;
- indicators and regimes are fully reproducible;
- no reconciliation failures;
- deterministic rerun produces identical results.

If these minimums are not met, status is `INSUFFICIENT_VALIDATION_SAMPLE` rather than pass/fail.

## 7. Design-freeze stage before validation

Before reading independent validation performance, create a separate frozen specification for `Breakout Retest v2` that defines all executable behavior.

That specification must include at minimum:

- exact entry rules;
- exact definition of structural failure;
- exact transition into `FAILURE_WATCH`;
- exact recovery condition;
- exact deterioration/forced-exit condition;
- exact maximum watch duration, if any;
- exact N/N+1 causal execution semantics;
- TP/SL/trailing behavior while in `FAILURE_WATCH`;
- max-holding behavior;
- interaction with TREND_DOWN;
- Risk Engine interaction;
- commission and slippage model;
- strategy version string;
- state persistence/recovery behavior;
- unit tests for every state transition.

No value in this specification may be altered after the independent validation sample is opened.

## 8. Mandatory strategy-state model

If `FAILURE_WATCH` is implemented, the strategy state machine must be explicit and testable.

Conceptual states:

```text
NORMAL_POSITION
    |
    | structural failure condition
    v
FAILURE_WATCH
    |                    |
    | recovery           | deterioration / timeout / existing hard exit
    v                    v
NORMAL_POSITION        CLOSE_SIGNAL
```

The final transition rules are not defined in this document and must be frozen separately before validation.

Strategy code must still obey the existing architecture:

```text
Market Data
→ Indicators
→ Market Regime
→ Strategy Signal / State Transition
→ Risk Engine
→ Execution Engine
→ Exchange
```

The strategy must not call the exchange or send orders directly.

## 9. Causality requirements

Independent validation is invalid if any rule uses future information.

Required semantics:

- state changes are based only on completed candles;
- a condition known on candle N may execute no earlier than candle N+1 open unless the existing backtest specification explicitly supports a causal intrabar order already active before the candle;
- no future high/low may be used to classify a state at an earlier timestamp;
- future MFE/MAE may appear only in attribution reports, never in live strategy logic;
- the final unfilled signal at dataset end is ignored;
- end-of-backtest liquidation remains explicit.

## 10. Required comparison set

Independent validation must compare at least:

1. `Breakout Retest v1` — frozen control.
2. `Breakout Retest v2` — frozen candidate.

Both must run on exactly the same:

- candles;
- symbols;
- timestamps;
- commission model;
- slippage model;
- random seed policy;
- initial balance;
- Risk Engine limits;
- walk-forward/test segmentation.

No parameter optimization is allowed inside the validation run.

## 11. Required metrics

Report per symbol and combined:

- closed trades;
- winners / losers;
- win rate;
- total PnL;
- profit factor;
- max drawdown;
- commissions;
- slippage cost;
- average holding bars;
- median holding bars;
- exit-reason attribution;
- `FAILURE_WATCH` entries;
- `FAILURE_WATCH` recoveries;
- `FAILURE_WATCH` exits;
- false-positive watch events that later become winners;
- saved losses relative to v1;
- sacrificed winners relative to v1;
- profitable temporal segments;
- per-segment PnL delta versus v1.

Preserve trade-level signals, risk decisions, orders, fills, state transitions, and parameters in artifacts.

## 12. Frozen acceptance gates

`Breakout Retest v2` may be classified as `VALIDATION_PASS_CANDIDATE` only if **all** gates below pass on independent data:

1. BTC v2 PnL > BTC v1 PnL.
2. ETH v2 PnL > ETH v1 PnL.
3. Combined v2 PnL > combined v1 PnL.
4. Combined v2 PnL > 0.
5. Neither symbol has materially worse max drawdown than v1.
6. Combined closed trades >= 30.
7. Each symbol closed trades >= 10.
8. Improvement is not dependent on one symbol.
9. Improvement is not dependent on one temporal segment.
10. Profitable temporal segments are not fewer than v1 combined.
11. Saved losers > sacrificed winners.
12. Zero causal failures.
13. Zero reconciliation failures.
14. Zero determinism failures.
15. Full unit/regression suite passes.

If any gate fails, status is `VALIDATION_REJECTED`.

No failed gate may be repaired by tuning on the opened validation sample.

## 13. One-shot validation rule

The independent validation sample is opened once.

After the first result is produced:

- do not change thresholds;
- do not change horizons;
- do not add/remove indicators;
- do not create BTC-only or ETH-only variants;
- do not change state-transition timing;
- do not rerun multiple candidate variants and choose the best one.

If the candidate fails, record the failure and start a new research cycle using a new future validation sample.

## 14. Engineering gates before validation

Before running the independent validation:

- complete unit tests for v2 state transitions;
- run the full existing regression suite;
- confirm v1 reproduction remains unchanged;
- confirm no changes to Risk Engine limits;
- confirm spot-only behavior;
- confirm Decimal-based monetary calculations;
- confirm UTC timestamps;
- confirm deterministic seed handling;
- confirm all generated orders have deterministic/unique client-order semantics where applicable;
- confirm no strategy code accesses the exchange directly;
- confirm `TRADING_MODE` safety remains unchanged.

## 15. Paper/live policy

A successful independent validation does **not** authorize live trading.

Required sequence remains:

```text
independent backtest validation
→ walk-forward confirmation
→ paper trading
→ monitoring/reconciliation validation
→ emergency-stop validation
→ only then possible live pilot
```

Live pilot remains capped by the project safety rules and is not part of this validation plan.

## 16. Decision statuses

Use only the following statuses for this stage:

- `PLAN_FROZEN`
- `INSUFFICIENT_VALIDATION_SAMPLE`
- `VALIDATION_PASS_CANDIDATE`
- `VALIDATION_REJECTED`
- `ENGINEERING_BLOCKED`

Do not use `PAPER_READY` or `LIVE_READY` as a result of this document alone.

## 17. Current status at freeze

```text
Breakout Retest v1 research OOS       RESEARCH_EXHAUSTED
Immediate 24h early exit              REJECTED UNIVERSAL RULE
Structural 24h immediate exit         REJECTED UNIVERSAL RULE
False-positive attribution            COMPLETE
Current regression                    259 tests passed in latest user run
Paper                                  BLOCKED
Live                                   BLOCKED

Next stage                             DESIGN Breakout Retest v2
Independent validation                 NOT STARTED
Validation plan                        PLAN_FROZEN
```

## 18. Next implementation step

The next code-producing step is **not** another diagnostic on the exhausted OOS sample.

The next step is to create a separate frozen `Breakout Retest v2` strategy specification that defines the full `FAILURE_WATCH` state machine **before** any independent validation data are inspected.

Only after that specification is frozen should implementation and tests begin.
