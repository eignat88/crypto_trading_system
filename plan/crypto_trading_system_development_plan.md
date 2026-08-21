# План развития Crypto Trading System

> Документ синхронизирован 21.08.2026. Детальный оперативный план находится в
> [`DEVELOPMENT_PLAN_2026-08-19.md`](DEVELOPMENT_PLAN_2026-08-19.md), а компактная
> последовательность milestones — в [`ROADMAP.md`](ROADMAP.md).

## Цель текущего цикла

Доказать эксплуатационную готовность собранного **paper application**: проверить
непрерывный источник на стенде, проверить уже встроенные emergency stop и
reconciliation, провести soak и настроить внешний watchdog/alerts.
До прохождения paper acceptance gates live trading остаётся запрещённым.

## Что уже построено

1. **Данные:** RAW/DDS, проверки качества, checkpoints, versioned derived data,
   инкрементальные indicators/regime и идемпотентный DDS → MART ETL.
2. **Исследование:** backtest с N → N+1 execution, costs, portfolio, audit trail и
   walk-forward foundation.
3. **Стратегии и risk:** Trend DCA, Breakout Retest, frozen v2 и Risk Engine.
4. **Paper application:** composition root/CLI, preflight, restore, Bybit REST →
   RAW → DDS closed-candle feed, warmup, managed pipeline, fill simulation,
   PostgreSQL persistence, PnL и shutdown checkpoint.
5. **Эксплуатационная база:** Python 3.12 CI, PostgreSQL 17 integration и единый
   checksum-protected migration runner.
6. **Independent validation:** sealed holdout pipeline с запретом performance до
   `2027-02-06T00:00:00Z` и выполнения sample requirements.

Restart/idempotency E2E реализован для sequence, order/fill и PnL restore. Production
builder использует long-running Bybit source, а календарное окно и Windows Task
Scheduler scripts готовы в коде. Наличие компонентов всё равно не равно готовности к
пилоту: не выполнены внешний alert routing, operator walkthrough и фактический
24–72-часовой soak.

## Приоритеты

### P0. Long-running paper validation

- [x] подключить long-running closed-candle source к готовому composition root;
- проверить source и scheduled session на целевом стенде;
- [x] встроить monitors и emergency stop в runtime loop;
- [x] выполнить fault-injection tests;
- выполнить smoke и 24–72-часовой soak;
- подтвердить graceful restart, monotonic sequence и отсутствие дублей.

### P0. Idempotency и recovery

- [x] restart E2E для sequence/order/fill/PnL/checkpoint;
- [x] deterministic client order identity и duplicate-order protection;
- [x] единые operational `run_id`/`signal_id` и синтетический restart self-check;
- [ ] стендовый restart production runtime во время soak.

### P1. Observability и reconciliation

- [x] durable heartbeat, health monitors, soak metrics/report и emergency-stop primitive;
- [x] automatic health triggers и сверка orders/fills/positions/equity/last event;
- [x] runbook и fault-injection;
- [ ] external alerts, freshness watchdog и operator walkthrough.

### P1. Reporting и pilot

- production scheduling для готовых market и MART pipelines (обёртка готова);
- [x] immutable daily report;
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
