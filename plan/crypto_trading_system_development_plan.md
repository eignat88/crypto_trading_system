# План развития Crypto Trading System

> Документ синхронизирован 20.08.2026. Детальный оперативный план находится в
> [`DEVELOPMENT_PLAN_2026-08-19.md`](DEVELOPMENT_PLAN_2026-08-19.md), а компактная
> последовательность milestones — в [`ROADMAP.md`](ROADMAP.md).

## Цель текущего цикла

Доказать эксплуатационную готовность собранного **paper application**: подключить
непрерывный источник, встроить watchdog/emergency stop, провести soak и добавить reconciliation.
До прохождения paper acceptance gates live trading остаётся запрещённым.

## Что уже построено

1. **Данные:** RAW/DDS, проверки качества, checkpoints, versioned derived data,
   инкрементальные indicators/regime и идемпотентный DDS → MART ETL.
2. **Исследование:** backtest с N → N+1 execution, costs, portfolio, audit trail и
   walk-forward foundation.
3. **Стратегии и risk:** Trend DCA, Breakout Retest, frozen v2 и Risk Engine.
4. **Paper application:** composition root/CLI, preflight, restore, warmup,
   managed pipeline, fill simulation, PostgreSQL persistence, PnL и shutdown checkpoint.
5. **Эксплуатационная база:** Python 3.12 CI, PostgreSQL 17 integration и единый
   checksum-protected migration runner.
6. **Independent validation:** sealed holdout pipeline с запретом performance до
   `2027-02-06T00:00:00Z` и выполнения sample requirements.

Restart/idempotency E2E реализован для sequence, order/fill и PnL restore. Наличие
компонентов всё равно не равно готовности к пилоту: production builder пока использует
пустой конечный event source, нет runtime wiring всех health triggers, внешнего alert
routing, полного reconciliation и фактического 24–72-часового soak.

## Приоритеты

### P0. Long-running paper validation

- подключить long-running closed-candle source к готовому composition root;
- встроить monitors и emergency stop в runtime loop;
- выполнить smoke, fault-injection и 24–72-часовой soak;
- подтвердить graceful restart, monotonic sequence и отсутствие дублей.

### P0. Idempotency и recovery

- [x] restart E2E для sequence/order/fill/PnL/checkpoint;
- [x] deterministic client order identity и duplicate-order protection;
- [ ] единые operational `run_id`/`signal_id` и стендовый restart во время soak.

### P1. Observability и reconciliation

- [x] durable heartbeat, health monitors, soak metrics/report и emergency-stop primitive;
- [ ] automatic triggers, external alerts и freshness watchdog;
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
