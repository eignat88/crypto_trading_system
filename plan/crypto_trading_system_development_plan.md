# План развития Crypto Trading System

> Документ синхронизирован 19.08.2026. Детальный оперативный план находится в
> [`DEVELOPMENT_PLAN_2026-08-19.md`](DEVELOPMENT_PLAN_2026-08-19.md), а компактная
> последовательность milestones — в [`ROADMAP.md`](ROADMAP.md).

## Цель текущего цикла

Собрать реализованные data, strategy, risk, paper execution, persistence,
monitoring и reporting компоненты в единый воспроизводимый **paper application**.
До прохождения paper acceptance gates live trading остаётся запрещённым.

## Что уже построено

1. **Данные:** RAW/DDS, проверки качества, checkpoints, versioned derived data,
   инкрементальные indicators/regime и идемпотентный DDS → MART ETL.
2. **Исследование:** backtest с N → N+1 execution, costs, portfolio, audit trail и
   walk-forward foundation.
3. **Стратегии и risk:** Trend DCA, Breakout Retest, frozen v2 и Risk Engine.
4. **Paper foundation:** market feed, fill simulation, execution runtime,
   PostgreSQL persistence/recovery, metrics, PnL и persistent PnL snapshots.
5. **Эксплуатационная база:** Python 3.12 CI, PostgreSQL 17 integration и единый
   checksum-protected migration runner.
6. **Independent validation:** sealed holdout pipeline с запретом performance до
   `2027-02-06T00:00:00Z` и выполнения sample requirements.

Наличие компонентов не равно готовности к пилоту: пока нет application lifecycle,
полного reconciliation, alert routing и доказанного restart E2E.

## Приоритеты

### P0. Paper composition и lifecycle

- composition root/CLI;
- preflight, schema compatibility, restore, warmup;
- closed-candle processing через Strategy → Risk → Execution;
- durable checkpoints и graceful shutdown;
- fail-closed отказ при live mode и критической зависимости.

### P0. Idempotency и recovery

- restart E2E на границах signal/order/fill/PnL/checkpoint;
- deterministic replay;
- correlation identifiers и запрет duplicate orders.

### P1. Observability и reconciliation

- heartbeat, lag/latency/checkpoint/risk/PnL metrics;
- alerts и emergency stop;
- сверка orders/fills/positions/equity/last event;
- runbook и fault-injection.

### P1. Reporting и pilot

- production scheduling для готовых market и MART pipelines;
- immutable daily report;
- фиксированная pilot configuration;
- 7-day burn-in и минимум 90 дней/100 закрытых сделок.

## Решения до старта paper pilot

- одна pilot strategy и её immutable version;
- capital/exposure/loss/drawdown limits;
- candle-lag, recovery-time и alert-delivery SLO;
- hosting, PostgreSQL backup/restore и log retention;
- владелец emergency stop и процедура его снятия.

## Definition of Done

Изменение считается готовым, если оно типизировано, покрыто unit/integration
проверками на соответствующих границах, идемпотентно после restart, не раскрывает
секреты, оставляет audit trail, обновляет документацию и не ослабляет live/holdout
gates.

## Запрещённые сокращения пути

- Не вызывать exchange напрямую из стратегии.
- Не обрабатывать незакрытую свечу как финальную.
- Не исправлять неоднозначное reconciliation mismatch автоматически.
- Не анализировать performance sealed holdout до unlock.
- Не добавлять Grid/ML/leverage/live execution в текущий цикл.
