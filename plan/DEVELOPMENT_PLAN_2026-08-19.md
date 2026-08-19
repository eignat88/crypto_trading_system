# План разработки Crypto Trading System на 19.08.2026

## 1. Резюме

Система уже имеет рабочее исследовательское ядро и значительную часть paper-контура,
но пока не готова ни к длительному paper-запуску, ни тем более к live trading.
Главная задача ближайшего цикла — не добавлять новые стратегии, а превратить
существующие разрозненные компоненты в один воспроизводимый, наблюдаемый и
fail-closed paper runtime.

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
- Paper-компоненты: market-data feed, exchange/fill simulation, execution engine,
  runtime, PostgreSQL repositories, recovery state, метрики и PnL reporting.
- Единая цепочка миграций в `database/migrations/` и checksum-protected runner
  `scripts/migrate_database.py` с журналом `public.schema_migrations`.
- Идемпотентный pipeline `RAW → DDS → indicators/regime` и отдельный
  идемпотентный DDS → MART ETL для отчётных агрегатов.
- Персистентные paper PnL snapshots вместе с orders, fills, positions и runtime
  state.
- CI с Ruff, unit-тестами и отдельной PostgreSQL 17 integration job.

### Реализовано частично или не интегрировано

1. `app/main.py` проверяет БД, но не собирает и не запускает paper runtime.
2. Общий market pipeline реализован как библиотечная композиция, но ещё не
   подключён к расписанию/основному runnable-приложению.
3. DDS → MART ETL реализован и протестирован, однако production-расписание и
   immutable daily-report delivery ещё не настроены.
4. Paper monitoring и reporting реализованы как библиотечные компоненты, но нет
   операционного процесса: health endpoint/heartbeat, alert routing, runbook и
   автоматический аварийный останов.
5. Нет exchange reconciliation и live order manager. Live режим должен оставаться
   запрещённым.
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

### P0 — собрать runnable paper application (19–26 августа)

- Добавить явный composition root/CLI для `PaperMarketData`, стратегии,
  `RiskEngine`, `PaperExecutionEngine`, repositories, metrics и PnL tracker.
- Реализовать lifecycle: startup preflight → restore → reconcile local state →
  warmup → consume closed candles → checkpoint → graceful shutdown.
- Гарантировать идемпотентность candle/event/order processing после рестарта.
- Подключить реализованный pipeline RAW → DDS → indicators/regime к composition
  root с общей
  границей `as_of` и запретом обработки незакрытой свечи.
- Добавить end-to-end тест restart в точках до/после signal, order и fill.

**Критерий выхода:** 24-часовой локальный/стендовый soak проходит без дублей,
расхождений позиции и пропущенных закрытых свечей; live mode продолжает завершаться
безопасным отказом.

### P1 — наблюдаемость и аварийное управление (26–29 августа)

- Определить обязательные метрики: heartbeat, candle lag, last closed candle,
  pipeline latency, rejected signals, orders/fills, exposure, PnL/drawdown,
  checkpoint age и recovery/reconciliation failures.
- Добавить structured event correlation (`run_id`, `signal_id`, `client_order_id`).
- Реализовать alerts и fail-closed emergency stop при stale data, DB outage,
  превышении risk limits и state mismatch.
- Подготовить runbook запуска, остановки, восстановления и расследования инцидента.

**Критерий выхода:** fault-injection тесты подтверждают, что каждый критический
сбой блокирует новые входы, сохраняет диагностический след и допускает безопасное
восстановление.

### P1 — paper reconciliation и отчётность (29 августа – 2 сентября)

- Реализовать периодическую сверку orders, fills, positions, balance/equity и
  последнего обработанного market event.
- Классифицировать расхождения на recoverable/fatal; автоматическое исправление
  разрешить только для однозначных случаев.
- Подключить реализованный DDS → MART ETL к расписанию и immutable daily report.
- Формировать ежедневный immutable report с комиссиями, slippage, drawdown,
  rejection reasons и reconciliation status.

**Критерий выхода:** deterministic replay даёт одинаковые state/PnL/report;
искусственно внесённое расхождение обнаруживается до следующего нового входа.

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
| 3 | Paper composition/lifecycle | 1, 2 | Запускаемое paper-приложение |
| 4 | Restart/idempotency E2E | 3 | Безопасное восстановление |
| 5 | Monitoring/emergency stop | 3 | Fail-closed эксплуатация |
| 6 | Reconciliation | 4, 5 | Доказуемая согласованность состояния |
| 7 | MART/daily report | 2, 3 | Операционная отчётность |
| 8 | 90-дневный paper pilot | 4–7 | Данные для решения о следующей фазе |
| 9 | Live design review | 8 | Отдельный go/no-go, без автозапуска |

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
