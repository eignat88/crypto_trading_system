# Роадмэп Crypto Trading System

**Срез:** 21.08.2026.
**Источник текущих приоритетов:** [`DEVELOPMENT_PLAN_2026-08-19.md`](DEVELOPMENT_PLAN_2026-08-19.md).
**Текущий milestone:** доказать эксплуатационную готовность paper-контура. Live trading заблокирован.

## Выполненный foundation

- [x] Python 3.12 local/CI baseline и PostgreSQL 17 integration job.
- [x] Идемпотентные RAW → DDS → indicators/regime и DDS → MART pipelines.
- [x] Backtest/walk-forward, стратегии, Risk Engine и sealed holdout pipeline.
- [x] Paper execution, PostgreSQL persistence, PnL snapshots и checksum-protected migrations.
- [x] Единственный paper composition root с preflight, restore, warmup и graceful shutdown.
- [x] Managed closed-candle pipeline до paper execution.
- [x] Restart/idempotency E2E для sequence, checkpoint, order/fill и PnL restore.
- [x] Durable heartbeat, health monitors, notifier abstraction и emergency-stop primitive.
- [x] Ограниченный soak runner и JSON evidence report.
- [x] Production Bybit REST → RAW → DDS closed-candle source с bootstrap,
  восстановлением gaps, polling и durable resume boundary.
- [x] Настраиваемое окно paper-сессии и Windows Task Scheduler scripts.

## Milestone M1 — runnable paper application (код завершён)

- [x] Fail-closed startup и проверка migration 050.
- [x] Restore runtime/risk/orders/fills/positions/PnL до обработки событий.
- [x] EMA200 warmup gate и обработка только закрытых свечей.
- [x] Durable checkpoint и signal-aware shutdown.
- [x] Безопасный отказ для любого режима кроме `paper`.

**Открытый gate:** production dependency builder уже использует long-running Bybit
source; требуется короткий стендовый smoke с реальной PostgreSQL и подтверждение
корректного завершения/повторного запуска по расписанию.

## Milestone M2 — restart/idempotency (код завершён, стендовый gate открыт)

- [x] E2E restart вокруг runtime state, sequence, order/fill и PnL snapshot.
- [x] Детерминированный `client_order_id` и защита от повторного ордера после restore.
- [x] Durable managed-pipeline checkpoint и повторная обработка без изменения факта.
- [x] Единый paper `run_id`/`signal_id` во все operational events (DB migration 051).
- [ ] Выполнить управляемый restart в 24–72-часовом PostgreSQL soak.

## Milestone M3 — observability и fail-closed operation (код завершён)

- [x] Persistent heartbeat в `monitoring.runtime_health`.
- [x] Database, market, pipeline и risk health monitors.
- [x] Console notifier и идемпотентный emergency-stop coordinator.
- [x] Soak session/metrics/JSON report и CLI `scripts/run_paper_soak.py`.
- [x] HealthCoordinator: wiring monitors → RiskEngine → EmergencyStop → Notifier.
- [x] Fault-injection тесты для DB outage, stale data, risk breach и state mismatch.
- [ ] Настроить внешний alert routing и freshness watchdog (health endpoint либо supervisor).
- [ ] Подготовить operational/incident runbook и процедуру снятия stop.
- [ ] Проверить Windows scheduled task, границы торгового окна и автоматический
  restart на целевом хосте.

**Выход:** 24–72 часа с живым источником, без дублей/пропусков, с доказанным
автоматическим fail-closed поведением и сохранённым evidence report.

## Milestone M4 — reconciliation и отчётность (код завершён)

- [x] PaperReconciler: сверка orders, fills, positions, balance/equity.
- [x] Классификация recoverable и fatal mismatches.
- [x] RiskEngine.update_reconciliation() блокирует новые входы при fatal.
- [x] DailyReportGenerator: immutable JSON с reconciliation status, content hash.
- [x] Wire в PaperApplication: periodic reconciliation + HealthCoordinator.
- [ ] Подключить расписание MART ETL и daily report к cron/scheduler.

## Milestone M5 — paper pilot (минимум 90 дней)

- [ ] Зафиксировать strategy/version, universe, capital, risk limits, SLO и владельцев.
- [ ] Пройти 7-дневный burn-in без изменения стратегии.
- [ ] Накопить не менее 90 календарных дней и 100 закрытых сделок.
- [ ] Иметь ноль необъяснённых reconciliation/determinism failures и duplicate orders.
- [ ] Обеспечить alert/audit trail для каждого критического incident.
- [ ] Подтвердить положительный net PnL после costs и drawdown в утверждённом limit.

Прохождение M5 создаёт пакет для отдельного live design review, но не разрешает live автоматически.

## Постоянный поток — sealed holdout до 06.02.2027

- [x] Frozen v2 specification и unlock timestamp.
- [x] Инкрементальный ingestion/health/preflight pipeline.
- [ ] Продолжать техническую загрузку закрытых BTCUSDT/ETHUSDT 1h candles.
- [ ] Контролировать gaps, duplicates, provenance, checksums и determinism.
- [ ] После unlock и sample gate выполнить ровно один frozen run.

До unlock запрещены backtest, PnL, trade attribution и сравнение версий на holdout.

## Вне текущего scope

Grid, ML, futures, margin, leverage, short, HFT, auto-optimization и live order manager.
