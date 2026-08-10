# Breakout Retest v2 — frozen strategy specification

Status: DESIGN FROZEN BEFORE IMPLEMENTATION AND INDEPENDENT VALIDATION

Parameters version: `breakout_retest_v2`

Validation plan: `docs/breakout_retest_v2_independent_validation_plan.md`

## 1. Purpose

`Breakout Retest v2` preserves the complete entry logic and all existing hard-risk exits of `Breakout Retest v1` and adds one explicit position-management state: `FAILURE_WATCH`.

The design addresses one research conclusion from the exhausted v1 OOS sample:

- a structural breakdown can appear well before the existing `TREND_DOWN` exit;
- an immediate exit at the first structural-breakdown snapshot creates material false positives;
- some profitable trades undergo a genuine structural breakdown and later recover.

The v2 hypothesis is therefore:

> A position that shows structural failure after 24 completed hourly bars should enter a temporary `FAILURE_WATCH` state rather than close immediately. If the same structure is fully reclaimed during the watch, the position returns to normal management. If the structure is not reclaimed within one fixed 24-bar watch cycle, the strategy emits a close signal. Existing hard exits remain authoritative throughout the watch.

This document freezes the executable design before any independent validation sample is opened.

No values in this specification may be changed after independent validation begins.

## 2. Scope and unchanged v1 behavior

Scope remains:

- Bybit spot;
- BTCUSDT and ETHUSDT;
- 1h candles;
- long only;
- quote currency USDT/USDC;
- no leverage, margin or futures;
- no DCA;
- strategy emits signals/state transitions only;
- Risk Engine and Execution Engine remain external and authoritative.

The following v1 behavior is unchanged:

- resistance lookback: 20 completed candles;
- retest timeout: 24 completed candles;
- breakout and retest definitions;
- entry context filters;
- base position target: 2.5% of capital before Risk Engine adjustments;
- stop-loss: 15%;
- take-profit: 5%;
- trailing activation: 3%;
- trailing distance: 2%;
- max holding: 100 candles;
- exit on `TREND_DOWN`;
- DCA disabled;
- next-candle-open execution semantics;
- commission/slippage model;
- Risk Engine limits;
- end-of-backtest liquidation behavior.

If this document does not explicitly change a v1 rule, the v1 rule remains in force.

## 3. Frozen v2 design parameters

The following values are frozen before independent validation:

- `failure_detection_age_bars = 24` completed hourly position bars;
- `failure_watch_max_bars = 24` completed hourly watch bars;
- `max_failure_watch_episodes_per_position = 1`;
- structural failure requires all three strict conditions:
  - `close < EMA20`;
  - `close < EMA50`;
  - `close < breakout_level`;
- structural recovery requires all three strict reclaim conditions:
  - `close >= EMA20`;
  - `close >= EMA50`;
  - `close >= breakout_level`;
- failure-watch timeout emits `CLOSE`;
- no numeric tolerance or percentage buffer is used;
- no ATR, volatility, RSI, EMA slope, MFE, MAE, regime-confidence or symbol-specific condition is used by the new state machine.

`24` bars for detection and `24` bars for watch duration are design assumptions representing one completed trading-day cycle on 1h data. They are not claimed to be optimal values.

No `6/12/18/36/48h` alternative may be evaluated on the independent validation sample.

## 4. Required strategy state

Per symbol, v2 must persist the existing entry/setup state plus explicit position-management state.

Entry/setup state remains conceptually:

- `IDLE`;
- `BREAKOUT_ARMED`.

Open-position management state is:

- `NORMAL_POSITION`;
- `FAILURE_WATCH`.

Persistent position-management fields:

- `position_state`;
- `position_entry_fill_time`;
- `position_entry_price`;
- `position_breakout_level`;
- `position_age_bars`;
- `failure_watch_used`;
- `failure_watch_start_time`;
- `failure_watch_bars`;
- `failure_watch_trigger_close`;
- `failure_watch_trigger_ema20`;
- `failure_watch_trigger_ema50`;
- `failure_watch_trigger_breakout_level`;
- `failure_watch_resolution`;
- `failure_watch_resolution_time`.

State must be instance-local, serializable, deterministic and restart-safe. No global mutable state is allowed.

## 5. Position state initialization

A BUY signal does not create position state by itself.

Only after the actual entry fill is confirmed through `on_fill`:

- set `position_state = NORMAL_POSITION`;
- persist actual entry fill time and actual fill price;
- persist the breakout level associated with that filled signal;
- set `position_age_bars = 0`;
- set `failure_watch_used = False`;
- clear all watch-specific fields.

If a BUY signal is rejected by Risk Engine or never filled, no position-management state may be created.

## 6. Position age semantics

The entry fill occurs at candle open.

The entry candle counts as completed position bar 1 when that candle closes.

Therefore:

- position bar 1 = entry candle;
- position bar 24 has `open_time = entry_fill_time + 23h`;
- structural failure is first eligible to be evaluated at the close of position bar 24;
- no structural-failure evaluation is permitted before bar 24.

`position_age_bars` increments exactly once per completed hourly candle while the position remains open.

## 7. Structural failure definition

Structural failure is evaluated only when all of the following are true:

1. an actual long position is open;
2. `position_state == NORMAL_POSITION`;
3. `position_age_bars >= 24`;
4. `failure_watch_used == False`;
5. current completed candle has valid EMA20 and EMA50;
6. persisted `position_breakout_level` is present and positive;
7. current `close < EMA20`;
8. current `close < EMA50`;
9. current `close < position_breakout_level`.

All three price-structure comparisons are strict.

Equality with any one level does not satisfy structural failure.

No PnL threshold, EMA slope, ATR, volatility, regime label or MFE/MAE value participates in the condition.

## 8. NORMAL_POSITION -> FAILURE_WATCH

When structural failure is true at candle N close:

- do **not** emit a close signal solely because of structural failure;
- transition `NORMAL_POSITION -> FAILURE_WATCH` after processing the completed candle;
- set `failure_watch_used = True` immediately;
- set `failure_watch_start_time = candle N open_time`;
- set `failure_watch_bars = 0`;
- persist trigger close, EMA20, EMA50 and breakout level;
- emit an auditable state-transition event with reason `Structural failure watch started`.

No order is generated by this transition.

The state becomes effective for the next candle.

## 9. One watch episode per position

Each filled position may enter `FAILURE_WATCH` at most once.

After `failure_watch_used` becomes true it remains true until that position is fully closed.

If the position later recovers to `NORMAL_POSITION` and then structurally fails again, v2 does **not** start a second watch episode and does not emit a new failure-watch close solely from the repeated condition.

Rationale: one-shot watch behavior prevents oscillation, repeated timeout resets and hidden degrees of freedom before independent validation.

A new position created by a later independent entry starts with `failure_watch_used = False`.

## 10. FAILURE_WATCH bar counting

The structural-failure trigger candle is not watch bar 1.

The first completed candle after entering `FAILURE_WATCH` is watch bar 1.

On each later completed candle while the position remains open and `position_state == FAILURE_WATCH`:

1. increment `failure_watch_bars` by exactly 1;
2. apply existing hard-exit precedence from section 13;
3. if no hard exit closes the position, evaluate recovery;
4. if no recovery occurs, evaluate timeout.

The watch may therefore observe at most 24 completed candles after the structural-failure trigger candle.

## 11. Recovery definition

Recovery is intentionally the logical mirror of the three-level structural-failure condition.

A completed watch candle is a valid recovery only when all are true:

- `close >= EMA20`;
- `close >= EMA50`;
- `close >= position_breakout_level`.

No percentage tolerance is allowed.

No EMA slope, regime, ATR, volatility, MFE, MAE or PnL requirement is allowed.

If recovery is true:

- transition `FAILURE_WATCH -> NORMAL_POSITION`;
- set `failure_watch_resolution = RECOVERED`;
- persist `failure_watch_resolution_time`;
- retain `failure_watch_used = True`;
- clear the active watch counter or mark it inactive;
- emit no order solely because recovery occurred.

Normal v1 position management then continues.

Because only one watch episode is allowed, later structural failure does not re-arm the watch.

## 12. FAILURE_WATCH timeout -> CLOSE_SIGNAL

If, after incrementing for the current completed watch candle:

- recovery is false; and
- `failure_watch_bars >= 24`; and
- the position is still open; and
- no higher-priority hard exit already owns the close;

then emit exactly one SELL/CLOSE signal with reason:

`Failure watch timeout without structural recovery`.

The timeout signal is generated at the close of watch bar 24.

It is eligible for execution only at the next candle open (`N+1`) through the existing Risk/Execution pipeline.

The strategy must not assume the position is closed until an actual fill is received.

If the dataset ends before N+1, the close signal remains unfilled and existing end-of-backtest liquidation semantics apply.

## 13. Hard-exit precedence while in FAILURE_WATCH

`FAILURE_WATCH` does not suspend or weaken existing safety exits.

The following existing exits remain active with unchanged semantics:

- 15% stop-loss;
- 5% take-profit;
- trailing stop after existing 3% activation with 2% distance;
- `TREND_DOWN` exit;
- max holding 100 bars;
- end-of-backtest liquidation.

Intrabar engine-owned stop/TP/trailing processing keeps its current precedence and causal rules.

If an existing hard exit closes the position before recovery or timeout:

- no recovery transition is processed afterward;
- no failure-watch timeout signal is emitted;
- mark `failure_watch_resolution` using the actual hard-exit category;
- reset position state only after actual fill/engine-confirmed close according to the existing lifecycle.

`FAILURE_WATCH` is never allowed to delay an existing stop-loss, take-profit, trailing, TREND_DOWN or max-holding exit.

## 14. TREND_DOWN interaction

The existing v1 rule remains unchanged:

- if the completed candle regime is `TREND_DOWN`, the strategy emits the existing TREND_DOWN close signal according to current semantics.

This applies in both `NORMAL_POSITION` and `FAILURE_WATCH`.

TREND_DOWN has priority over failure-watch recovery and timeout on the same completed candle.

No confirmation bars or alternative regime threshold are introduced in v2.

## 15. Max-holding interaction

The v1 maximum holding period remains 100 candles from actual entry fill.

Entering `FAILURE_WATCH` does not reset or extend max holding.

Returning to `NORMAL_POSITION` after recovery does not reset or extend max holding.

If max holding is reached during the watch, the existing max-holding close takes priority over recovery or watch timeout on that candle.

## 16. TP, SL and trailing interaction

No TP/SL/trailing value changes in v2.

While `FAILURE_WATCH` is active:

- stop-loss remains 15%;
- take-profit remains 5%;
- trailing activation remains 3%;
- trailing distance remains 2%;
- existing high-water/trailing state continues from the original position lifecycle;
- entering watch must not reset trailing activation, high-water marks or any engine-owned exit state;
- recovery must not reset them either.

No special tighter stop is added during watch.

## 17. DCA remains disabled

Breakout Retest v2 must never emit DCA/add-to-position signals.

This applies in both `NORMAL_POSITION` and `FAILURE_WATCH`.

A structurally impaired breakout must not be averaged down.

## 18. Entry behavior while a position is open

No new breakout/retest entry may be armed while the strategy already has an open position in that symbol.

`FAILURE_WATCH` does not permit pyramiding, replacement entry or hedge behavior.

The existing one-position-per-symbol semantics remain unchanged.

## 19. Risk Engine interaction

Risk Engine remains independent and authoritative.

v2 cannot bypass or weaken:

- free capital checks;
- maximum position allocation;
- per-asset exposure;
- total utilization;
- daily loss limit;
- weekly loss limit;
- maximum drawdown limit;
- data freshness;
- API health;
- PostgreSQL health;
- reconciliation status;
- emergency stop.

A strategy-generated close signal still travels through the normal execution pipeline.

No strategy code may call the exchange directly.

## 20. Causal timing requirements

All new v2 transitions use completed candles only.

Required semantics:

- structural failure on candle N is known only after candle N closes;
- `FAILURE_WATCH` becomes active for subsequent candle processing;
- recovery on candle M is known only after M closes;
- recovery emits no trade;
- timeout on candle T is known only after T closes;
- timeout CLOSE may execute no earlier than T+1 open;
- no future high, low, close, EMA, regime or fill information may participate in prior state classification;
- future MFE/MAE is prohibited from strategy logic;
- the final unfilled signal remains unfilled;
- end-of-backtest liquidation remains explicit and separately attributed.

## 21. Deterministic transition precedence

For each completed candle with an open position, processing order must be deterministic.

Conceptual precedence:

```text
1. engine-owned intrabar hard exits already triggered for the candle
2. existing explicit strategy hard exit: TREND_DOWN / max holding
3. if still open: update position age
4. if NORMAL_POSITION and watch unused: structural-failure detection
5. if FAILURE_WATCH already active from a prior candle:
     a. increment watch bars
     b. recovery check
     c. timeout check
6. persist state transition/audit record
```

A candle that **creates** `FAILURE_WATCH` cannot simultaneously count as watch bar 1 and cannot simultaneously recover from that newly-created watch.

A candle that satisfies recovery and reaches watch-bar 24 resolves as `RECOVERED`, because recovery is checked before timeout after higher-priority hard exits.

## 22. Position close and state reset

State reset occurs only after the position is actually closed according to the engine/fill lifecycle.

After full close:

- `position_state` returns to no-position/default state;
- entry-fill metadata is cleared;
- breakout level associated with the closed position is cleared;
- position age is cleared;
- watch fields are cleared;
- `failure_watch_used` resets for the next future position only.

A close signal without fill must not reset position state prematurely.

## 23. Restart and recovery requirements

If the process restarts while a position is open, persisted state must reconstruct exactly:

- whether the position is `NORMAL_POSITION` or `FAILURE_WATCH`;
- original actual entry fill time/price;
- persisted breakout level;
- position age;
- whether a watch was already used;
- watch start time;
- watch bars elapsed;
- trigger snapshot values;
- trailing/high-water state owned by existing components;
- last processed candle/open_time.

On recovery after restart, the same candle must never be processed twice for age or watch counters.

If state cannot be reconciled safely with local position/fill history, new orders must be blocked and the normal reconciliation/emergency-stop policy applies.

## 24. Required audit events

At minimum persist auditable records for:

- `POSITION_NORMAL_STARTED`;
- `FAILURE_WATCH_STARTED`;
- `FAILURE_WATCH_RECOVERED`;
- `FAILURE_WATCH_TIMEOUT_SIGNAL`;
- `FAILURE_WATCH_RESOLVED_BY_STOP_LOSS`;
- `FAILURE_WATCH_RESOLVED_BY_TAKE_PROFIT`;
- `FAILURE_WATCH_RESOLVED_BY_TRAILING`;
- `FAILURE_WATCH_RESOLVED_BY_TREND_DOWN`;
- `FAILURE_WATCH_RESOLVED_BY_MAX_HOLDING`;
- actual position close/fill event.

Each `FAILURE_WATCH_STARTED` event must include:

- symbol;
- strategy version;
- entry fill time;
- current candle time;
- position age;
- current close;
- EMA20;
- EMA50;
- persisted breakout level;
- current regime;
- reason code.

Each recovery/timeout event must include the corresponding current snapshot and watch-bar count.

## 25. Signal metadata

Every v2 signal must carry:

- `strategy = breakout_retest`;
- `parameters_version = breakout_retest_v2`;
- symbol;
- signal timestamp;
- direction/action;
- reason;
- relevant indicator/context snapshot;
- market regime;
- original breakout metadata for the position;
- position-management state;
- watch-used flag;
- watch-bar count when applicable.

Timeout CLOSE signals additionally require:

- watch start time;
- watch trigger snapshot;
- timeout candle time;
- recovery condition values at timeout.

## 26. Explicitly prohibited v2 behavior

The implementation must not:

- change v1 entry criteria;
- change resistance lookback;
- change retest timeout;
- add DCA;
- add symbol-specific behavior;
- add BTC-only or ETH-only branches;
- use `return < X` as a failure/recovery condition;
- use MFE/MAE in live strategy decisions;
- add EMA slope filters;
- add ATR/volatility filters to watch resolution;
- use alternative watch durations;
- repeatedly re-arm watch in the same position;
- reset max holding after recovery;
- reset trailing state after watch/recovery;
- suppress hard exits during watch;
- execute on the same close that generated a new timeout signal;
- inspect independent validation performance while changing this specification.

## 27. State-machine summary

```text
NO POSITION
    |
    | existing v1 breakout + retest + Risk + actual BUY fill
    v
NORMAL_POSITION
    |
    | after >=24 completed position bars
    | close < EMA20
    | close < EMA50
    | close < breakout_level
    | watch not previously used
    v
FAILURE_WATCH
    |
    |-- existing SL / TP / trailing / TREND_DOWN / max holding --> CLOSE
    |
    |-- full structural reclaim:
    |     close >= EMA20
    |     close >= EMA50
    |     close >= breakout_level
    |                                                  --> NORMAL_POSITION
    |
    |-- 24 completed watch bars without reclaim ------> CLOSE_SIGNAL

After RECOVERY:
NORMAL_POSITION continues,
but FAILURE_WATCH cannot be armed again for that position.
```

## 28. Unit-test acceptance criteria

Implementation is not ready until tests cover at least:

1. v1 entry behavior remains unchanged for equivalent candle streams;
2. actual BUY fill initializes `NORMAL_POSITION` state;
3. BUY signal without fill does not initialize position state;
4. structural failure cannot trigger before 24 completed position bars;
5. entry candle is position bar 1;
6. bar with open_time `entry+23h` is position bar 24;
7. structural failure requires close strictly below all EMA20, EMA50 and breakout level;
8. equality with EMA20 prevents failure trigger;
9. equality with EMA50 prevents failure trigger;
10. equality with breakout level prevents failure trigger;
11. structural failure enters watch but emits no close;
12. trigger candle does not count as watch bar 1;
13. first later completed candle increments watch to 1;
14. recovery requires reclaim of all three levels;
15. equality satisfies recovery because recovery uses `>=`;
16. partial reclaim does not recover;
17. recovery returns to normal without emitting an order;
18. recovery keeps `failure_watch_used=True`;
19. a recovered position cannot enter a second watch;
20. watch timeout occurs exactly after 24 completed watch bars;
21. timeout emits one close signal only;
22. timeout signal executes only through N+1 semantics;
23. final-candle timeout signal cannot create a fill without N+1;
24. TREND_DOWN during watch has priority over recovery/timeout;
25. max holding during watch has priority over recovery/timeout;
26. stop-loss remains active during watch;
27. take-profit remains active during watch;
28. trailing remains active during watch;
29. entering watch does not reset trailing/high-water state;
30. recovery does not reset max-holding age;
31. DCA is impossible in either position state;
32. full close resets watch state only after actual fill/confirmed close;
33. unfilled close signal does not reset state;
34. restart in `FAILURE_WATCH` restores exact counter/state;
35. replay of last processed candle does not double-increment counters;
36. BTC and ETH states are independent;
37. two strategy instances share no mutable state;
38. deterministic rerun produces identical transitions/signals/results;
39. v1 frozen reproduction remains unchanged in its own control run;
40. complete regression suite passes.

## 29. Pre-validation engineering gate

Before independent validation data are opened:

- implement v2 in a separately versioned strategy path/class/config without changing v1 behavior;
- add all transition tests from section 28;
- run full regression suite;
- reproduce frozen v1 control results;
- verify state persistence/restart behavior;
- verify exact N/N+1 timing;
- verify no future-data dependency;
- verify no change to Risk Engine defaults;
- verify no change to commission/slippage defaults;
- verify strategy has no exchange access;
- verify `TRADING_MODE` safety remains unchanged;
- create deterministic artifacts that record all state transitions.

If any engineering gate fails, status is `ENGINEERING_BLOCKED` and independent validation must not begin.

## 30. Independent validation protocol

Independent validation follows `docs/breakout_retest_v2_independent_validation_plan.md` exactly.

The validation comparison is:

- frozen `Breakout Retest v1` control;
- frozen `Breakout Retest v2` candidate from this document.

No parameters may be optimized inside validation.

Minimum sample and all acceptance/rejection gates from the validation plan remain binding.

## 31. Interpretation rule

This specification is intentionally a single candidate, not a family of variants.

After validation begins, prohibited responses to a failure include:

- changing 24h detection to 12h/18h/36h/48h;
- changing watch duration;
- adding EMA slope;
- adding return/MFE/MAE thresholds;
- loosening/tightening reclaim conditions;
- adding symbol-specific logic;
- permitting multiple watch episodes;
- selecting a better-looking variant from the same validation sample.

If any frozen validation gate fails, v2 is recorded as `VALIDATION_REJECTED` and a new research cycle requires new independent data.

## 32. Current status at freeze

```text
Breakout Retest v1                    FROZEN CONTROL
v1 historical research sample         RESEARCH_EXHAUSTED
v2 independent validation plan        PLAN_FROZEN
Breakout Retest v2 spec               DESIGN_FROZEN
v2 implementation                     NOT STARTED
v2 transition tests                   NOT STARTED
independent validation                NOT STARTED
paper                                 BLOCKED
live                                  BLOCKED
```

## 33. Next step

The next implementation step is to implement `Breakout Retest v2` exactly as specified here, with state-transition unit tests, **without opening or evaluating the independent validation sample**.

Implementation must preserve v1 as an unchanged frozen control.
