# План разработки Crypto Trading System

**Первичный аудит:** 19.08.2026. **Последняя актуализация:** 21.08.2026.

## 1. Резюме

Система имеет рабочее исследовательское ядро и собранный paper composition root,
но пока не готова к длительному paper pilot и тем более к live trading. Главная
задача цикла — проверить подключённый long-running источник на целевом стенде,
замкнуть health monitors на emergency stop/reconciliation и доказать поведение
24–72-часовым soak, а не добавлять стратегии.

Параллельно необходимо продолжать **только техническое** накопление sealed holdout
`Breakout Retest v2`. Просмотр performance-метрик этой выборки запрещён до
`2027-02-06T00:00:00Z` и до выполнения минимальных требований к выборке.

## 2. Фактическое состояние на дату аудита

### Реализовано

- RAW → DDS ETL, проверки качества, checkpoints и versioned derived data.
- Индикаторы, определение режима рынка и batch-расчёт derived-данных.
- Backtest с причинным исполнением N → N+1, комиссиями, проскальзыванием,
  портфелем, audit trail и walk-forward инфраструктурой.
- Стратегии Trend DCA и Breakout Retest, включая frozen-спецификацию v2.
- Risk Engine и сохранение risk state.
- Sealed holdout pipeline с health/preflight-проверками.
- Paper-компоненты: Bybit REST → RAW → DDS long-running market-data feed,
  exchange/fill simulation, execution engine,
  runtime, PostgreSQL repositories, recovery state, метрики и PnL reporting.
- Единая цепочка миграций в `database/migrations/` и checksum-protected runner
  `scripts/migrate_database.py` с журналом `public.schema_migrations`.
- Идемпотентный pipeline `RAW → DDS → indicators/regime` и отдельный
  идемпотентный DDS → MART ETL для отчётных агрегатов.
- Персистентные paper PnL snapshots вместе с orders, fills, positions и runtime
  state.
- CI с Ruff, unit-тестами и отдельной PostgreSQL 17 integration job.
- Paper CLI/composition root: fail-closed preflight, migration check, restore,
  warmup, managed closed-candle pipeline, checkpoint и graceful shutdown.
- PostgreSQL restart/idempotency E2E для sequence, order/fill, позиции и PnL;
  детерминированный `client_order_id` предотвращает повторный ордер.
- Persistent heartbeat, health monitors, notifier abstraction, emergency-stop
  coordinator, bounded soak runner и JSON evidence report.
- Настраиваемое календарное окно paper-сессии и PowerShell-скрипты запуска через
  Windows Task Scheduler.
- Операторский runbook, scheduled-task verifier, MART/daily-report wrapper и
  локальный синтетический restart-recovery self-check.

### Реализовано частично или не интегрировано

1. Штатный entry point `scripts/run_paper.py` подключён к long-running Bybit REST
   source с bootstrap/backfill, восстановлением gaps и polling закрытых 1h свечей;
   короткий прогон на целевой PostgreSQL ещё не выполнен.
2. Managed market pipeline подключён и протестирован, но его длительный запуск с
   реальным источником и целевой PostgreSQL ещё не доказан.
3. DDS → MART ETL и immutable report реализованы; PowerShell-обёртка готова, но
   production-расписание и подтверждённая доставка ещё не настроены.
4. HealthCoordinator, paper reconciliation, fault-injection tests и операторский
   runbook готовы. Остаются внешний alert routing/watchdog, operator walkthrough
   и стендовое evidence.
5. Exchange/live reconciliation и live order manager отсутствуют. Live режим
   должен оставаться запрещённым.
6. Полный lint debt и целевой PostgreSQL pilot остаются отдельными gates.

### Проверяемый baseline

- Актуальный объём unit suite определяется командой `python -m pytest tests/unit -q`;
  число тестов не используется как критерий готовности и не фиксируется вручную.
- Воспроизводимый baseline: Python 3.12, зависимости `.[dev]`, PostgreSQL 17 для
  integration suite.
- Ruff correctness-проверка должна соответствовать CI-команде, пока накопленный
  lint debt не выделен в отдельную задачу.

## 3. Принципы и ограничения

1. **Live запрещён по умолчанию.** До завершения paper acceptance gates никакие
   реальные ордера и секреты биржи не подключаются.
2. **Spot only:** BTCUSDT и ETHUSDT, без leverage, short и margin.
3. **Fail closed:** потеря БД, stale market data, ошибка recovery/reconciliation
   или нарушение risk limit запрещает новые входы.
4. **Один путь исполнения:** `Market Data → Indicators → Regime → Strategy →
   Risk Engine → Execution` без прямых вызовов exchange из стратегии.
5. **UTC и Decimal** сохраняются на всех границах системы.
6. **Holdout seal:** до разблокировки разрешены только ingestion, completeness,
   gaps, duplicates, provenance, reconciliation и determinism checks.
7. Новые стратегии, Grid, ML и оптимизация v2 не входят в этот план.

## 4. Приоритетный план

### P0 — сохранить воспроизводимый baseline (выполнено, контролируется CI)

- [x] Зафиксировать Python 3.12 как единый CI/local baseline; синхронизировать
  настройки Ruff и mypy с `requires-python`.
- [x] Установить `pip install -e ".[dev]"` и получить зелёный полный unit suite.
- [x] Запустить PostgreSQL integration suite на чистой PostgreSQL 17 в CI.
- [x] Удалить tracked backup-файлы и проверить отсутствие секретов/артефактов.
- [x] Обновить статусные документы по факту, исключив устаревшие утверждения о том,
  что Paper Exchange и recovery «не реализованы».

**Критерий выхода:** unit, Ruff correctness и PostgreSQL integration проходят из
чистого checkout; команды и версии среды записаны в CI и runbook.

### P0 — единые миграции и воспроизводимое состояние БД (выполнено)

- [x] Инвентаризировать все SQL-схемы и устранить конкурирующие каталоги.
- [x] Перенести paper orders, fills, positions, PnL snapshots и runtime state в один упорядоченный
  migration chain без destructive changes.
- [x] Добавить таблицу истории миграций, checksum и отказ при изменённой
  миграции.
- [x] Добавить unit/integration проверки применения и повторного запуска.

**Критерий выхода:** одна команда создаёт полную схему на пустой БД и безопасно
повторяется; runtime не стартует при несовместимой версии схемы.

### P0 — runnable paper application (код выполнен; стендовый gate открыт)

- [x] Добавить явный composition root/CLI для `PaperMarketData`, стратегии,
  `RiskEngine`, `PaperExecutionEngine`, repositories, metrics и PnL tracker.
- [x] Реализовать lifecycle: startup preflight → restore local state →
  warmup → consume closed candles → checkpoint → graceful shutdown.
- [x] Гарантировать идемпотентность sequence/order processing после рестарта.
- [x] Подключить реализованный pipeline RAW → DDS → indicators/regime к composition
  root с общей
  границей `as_of` и запретом обработки незакрытой свечи.
- [x] Добавить PostgreSQL E2E restart для runtime/checkpoint/order/fill/PnL restore.
- [x] Подключить long-running event source к production dependency builder.
- [x] Единый paper `run_id`/`signal_id` во все operational events (DB migration 051).
- [x] Добавить локальный синтетический restart-recovery self-check; не засчитывать
  его как runtime/PostgreSQL gate.
- [ ] Выполнить управляемый restart в soak и проверить resume boundary на стенде.

**Критерий выхода:** 24-часовой локальный/стендовый soak проходит без дублей,
расхождений позиции и пропущенных закрытых свечей; live mode продолжает завершаться
безопасным отказом.

### P0 — стендовый soak и эксплуатационная безопасность

- [x] Добавить bounded soak CLI, session model, heartbeat samples, lifecycle
  evidence и JSON report.
- [x] Подключить polling закрытых Bybit candles через RAW/DDS к production runtime.
- [x] Добавить fault-injection тесты для DB outage, stale data, risk breach и state mismatch.
- [ ] Доказать market throughput на стенде: отсутствие нового часового события не
  должно ошибочно считаться доказательством успешного soak.
- [ ] Сначала выполнить короткий smoke, затем 24–72 часа; во время прогона сделать restart.
- [ ] Проверить market throughput/gaps, monotonic sequence, checkpoint freshness,
  duplicate orders, позиции, PnL и сохранность evidence.

### P1 — наблюдаемость и аварийное управление

- [x] Определить и реализовать foundation метрик: heartbeat, candle lag,
  pipeline latency, rejected signals, orders/fills, exposure, PnL/drawdown,
  checkpoint age и recovery/reconciliation failures.
- [x] Добавить structured event correlation (`run_id`, `signal_id`, `client_order_id`).
- [x] Реализовать notifier interface и идемпотентный emergency-stop coordinator.
- [x] Связать alerts и fail-closed emergency stop срабатывающими при stale data, DB outage,
  превышении risk limits и state mismatch (HealthCoordinator).
- [x] Подготовить runbook запуска, остановки, восстановления и расследования инцидента.
- [ ] Провести operator walkthrough, заполнить escalation path и утвердить снятие stop.

**Критерий выхода:** fault-injection тесты подтверждают, что каждый критический
сбой блокирует новые входы, сохраняет диагностический след и допускает безопасное
восстановление. ✅ Выполнено (17 fault-injection тестов).

### P1 — paper reconciliation и отчётность (код завершён)

- [x] Реализовать периодическую сверку orders, fills, positions, balance/equity и
  последнего обработанного market event (PaperReconciler).
- [x] Классифицировать расхождения на recoverable/fatal; автоматическое исправление
  разрешить только для однозначных случаев.
- [x] Подготовить запуск DDS → MART ETL и immutable daily report
  (DailyReportGenerator) одной PowerShell-командой.
- [x] Формировать ежедневный immutable report с комиссиями, slippage, drawdown,
  rejection reasons и reconciliation status.
- [x] Wire в PaperApplication: periodic reconciliation + HealthCoordinator.
- [ ] Подключить расписание MART ETL и daily report к cron/scheduler.

**Критерий выхода:** deterministic replay даёт одинаковые state/PnL/report;
искусственно внесённое расхождение обнаруживается до следующего нового входа.
✅ Код выполнен, требуется стендовая проверка.

### P1 — контролируемый paper pilot (со 2 сентября, минимум 90 дней)

- Запустить BTCUSDT/ETHUSDT Spot на отдельной БД и с фиксированной конфигурацией.
- Первые 7 дней — наблюдаемый burn-in без изменения стратегии; затем основной
  непрерывный paper период.
- Еженедельно проверять availability, data gaps, incidents, reconciliation,
  drawdown и соответствие backtest/paper execution semantics.
- Любое изменение стратегии начинает новый сопоставимый период; исправления
  инфраструктуры документируются отдельно.

**Paper acceptance gates:**

- не менее 90 календарных дней и 100 закрытых сделок;
- ноль необъяснённых reconciliation/determinism failures;
- ноль повторных ордеров после рестарта;
- 100% критических инцидентов имеют alert и audit trail;
- положительный net PnL после комиссий и slippage;
- drawdown не превышает утверждённый risk limit;
- результаты не зависят только от одного символа или короткого периода.

Выполнение этих условий разрешает только отдельное решение о проектировании live,
а не автоматический переход к реальным деньгам.

### Постоянная задача — sealed holdout (до 06.02.2027)

- По расписанию загружать только закрытые BTCUSDT/ETHUSDT 1h свечи.
- Выполнять RAW/DDS/derived completeness, gap, duplicate, provenance и checksum
  проверки, сохраняя отчёты без performance-полей.
- Не запускать backtest, PnL, trade attribution или сравнение v1/v2 на holdout.
- После даты разблокировки сначала подтвердить минимальный размер и целостность
  выборки, затем выполнить ровно один frozen validation run.

## 5. Очерёдность backlog

| Порядок | Epic | Зависит от | Результат |
|---:|---|---|---|
| 1 | Baseline и hygiene | — | Достоверная зелёная точка отсчёта |
| 2 | Единые миграции | 1 | Воспроизводимая PostgreSQL schema |
| 3 | Paper composition/lifecycle | 1, 2 | Выполнено в коде |
| 4 | Restart/idempotency E2E | 3 | Выполнен тестовый baseline |
| 5 | Long-running source и soak | 3, 4 | Source готов; требуется стендовое evidence |
| 6 | Monitoring wiring/emergency stop | 5 | Fail-closed эксплуатация |
| 7 | Reconciliation | 4–6 | Доказуемая согласованность состояния |
| 8 | MART/daily report | 2, 3 | Операционная отчётность |
| 9 | 90-дневный paper pilot | 4–8 | Данные для решения о следующей фазе |
| 10 | Live design review | 9 | Отдельный go/no-go, без автозапуска |

## 6. Definition of Done для каждой задачи

- Есть типизированный контракт и явно описанное поведение при ошибке.
- Есть unit-тесты и, для границ с PostgreSQL/runtime, integration-тесты.
- Повторный вызов/рестарт не создаёт дублей и не изменяет уже подтверждённый факт.
- Логи не содержат секретов и включают correlation identifiers.
- Обновлены README/runbook/миграции и зафиксирована команда проверки.
- CI проходит на чистом checkout.
- Изменение не ослабляет holdout seal и live safety gate.

## 7. Решения, которые нужно принять до paper pilot

1. Какая стратегия является единственной pilot strategy: Trend DCA или отдельный
   frozen кандидат (не `Breakout Retest v2` на закрытом holdout).
2. Точные paper risk limits: initial capital, max position/exposure, daily/weekly
   loss и max drawdown.
3. Целевые SLO: допустимый candle lag, recovery time и alert delivery time.
4. Где работает pilot и PostgreSQL, как выполняются backup/restore и ротация логов.
5. Кто имеет право снять emergency stop и как документируется это действие.

До фиксации этих решений допустимы разработка и тестирование инфраструктуры, но
не старт отсчёта 90-дневного paper acceptance периода.
