# Статус проекта Crypto Trading System

## Текущий срез — 21.08.2026

Исследовательский и paper foundation реализованы. Текущий этап — **стендовая
валидация непрерывного paper runtime**. Дополнительно подготовлены операторский
runbook, проверка Windows scheduled task, обёртка MART/daily report и синтетический
restart-recovery self-check. Выполнены: structured event correlation,
HealthCoordinator (alerts + emergency stop wiring), PaperReconciler (runtime vs DB
state comparison), DailyReportGenerator (immutable JSON), fault-injection тесты.
Sealed holdout `Breakout Retest v2` для BTCUSDT/ETHUSDT 1h остаётся закрытым
для performance до `2027-02-06T00:00:00Z`.

## Матрица готовности

| Контур | Статус | Подтверждено в коде | Открытый gate |
|---|---|---|---|
| Python/CI | ✅ | Python 3.12, Ruff correctness, unit и PostgreSQL 17 jobs | Поддерживать CI |
| Data pipelines | ✅ Код готов | RAW/DDS quality/checkpoints, derived pipeline, MART ETL | Целевой PostgreSQL pilot и расписание |
| Backtest/strategies/risk | ✅ Ядро готово | Causal execution, costs, walk-forward, frozen v2, Risk Engine | Зафиксировать pilot candidate |
| Sealed holdout | 🚧 Накопление | Fail-closed update, health и preflight | Только технические проверки до unlock |
| Paper application | ✅ Код готов | CLI, preflight, restore, Bybit REST → RAW → DDS polling, warmup, managed pipeline, checkpoint, shutdown | Проверить production feed коротким стендовым soak |
| Restart/idempotency | ✅ Тестовый baseline | PostgreSQL E2E для sequence, orders/fills, PnL restore; duplicate-order guard; синтетический JSON self-check | Управляемый restart реального runtime во время soak |
| Event correlation | ✅ Код готов | run_id/signal_id в Signal, Order, Fill, RiskDecision, PaperOrderState, PaperFillState; DB migration 051 | Проверить на стенде |
| Monitoring | ✅ Foundation готов | Durable heartbeat, DB/market/pipeline/risk monitors, HealthCoordinator wiring | Runtime wiring завершён |
| Emergency stop | ✅ Код готов | Идемпотентная последовательность, HealthCoordinator → EmergencyStop, fault-injection тесты | Проверить на стенде |
| Reconciliation | ✅ Код готов | PaperReconciler (orders/fills/positions/balance), recoverable/fatal classification, RiskEngine integration | Проверить на стенде |
| Daily reporting | ✅ Код готов | DailyReportGenerator с reconciliation status, immutable JSON, content hash; PowerShell-обёртка MART + report | Установить расписание и проверить 7 последовательных запусков |
| Soak validation | 🚧 Runner готов | Bounded CLI, samples, lifecycle evidence, JSON report | 24–72 часа с живыми событиями |
| Scheduling | 🚧 Код готов | Настраиваемое окно paper-сессии, install/start и verification scripts для Windows Task Scheduler | Установить и проверить расписание на целевом хосте |
| Operations | ✅ Документация готова | Операторский `docs/RUNBOOK.md` и пошаговый acceptance runbook | Провести operator walkthrough и зафиксировать владельцев/escalation |
| Live execution | ⛔ Запрещено | Live mode отклоняется | Только отдельный go/no-go после pilot gates |

## Важные ограничения текущей реализации

1. `build_paper_dependencies()` использует long-running Bybit REST → RAW → DDS
   источник закрытых 1h свечей. Статический `PaperMarketData` сохранён только для
   детерминированных тестов; production-поток требует стендовой проверки с PostgreSQL.
2. HealthCoordinator и PaperReconciler подключены к runtime, но ещё не проверены
   на длинном стендовом прогоне с реальными данными.
3. Console notifier не является внешним alert routing.
4. Запуск расписания MART ETL и daily report ещё не подключён к cron/scheduler.
5. Предыдущие короткие `restart_before`/`restart_after` с sequence=0 не являются
   доказательством отказа: restart/idempotency остаётся проверить на событии X с
   ненулевым durable checkpoint. Реализовано, требуется проверка.
6. Календарное окно по умолчанию — будни 09:00–19:00 UTC; вне окна runtime
   безопасно не открывает сессию.
7. `test_paper_runtime_restart_recovery.py` проверяет локальную JSON-сериализацию
   искусственного состояния, но не production runtime/PostgreSQL restart gate.
8. Скрипты MART/report и scheduled-task verification подготовлены, но требуют
   evidence с целевого Windows-хоста.

## Следующие задачи по порядку

1. Выполнить короткий smoke soak long-running closed-candle source.
2. Провести 24–72-часовой стендовый soak с restart и подтверждением monotonic
   sequence, checkpoint и отсутствия duplicate `client_order_id`.
3. Проверить что HealthCoordinator, PaperReconciler и DailyReportGenerator
   корректно работают на длинном прогоне.
4. Установить расписание MART ETL и immutable daily report, затем подтвердить
   семь последовательных успешных запусков.
5. Выполнить целевой PostgreSQL data pilot и зафиксировать pilot configuration/SLO.
6. Провести operator walkthrough по готовому runbook, заполнить владельцев и
   escalation path.

## Воспроизводимые проверки

```bash
python --version
python -m ruff check . --select F --ignore F401,F841
python -m pytest tests/unit -q
python -m pytest tests/reporting -q
python scripts/test_paper_runtime_restart_recovery.py
```

PostgreSQL integration требует изолированной БД:

```bash
python scripts/migrate_database.py --database-url "$TEST_DATABASE_SQLALCHEMY_URL"
python -m pytest -m integration -q
```

Ограниченный soak после миграций запускается отдельно от pytest:

```bash
TRADING_MODE=paper python scripts/run_paper_soak.py \
  --duration-hours 24 \
  --symbols BTCUSDT ETHUSDT \
  --output-report artifacts/paper_soak_report.json
```

## Safety gates

- Live запрещён до минимум 90 дней/100 закрытых paper-сделок и отдельного решения.
- DB outage, stale data, risk breach или reconciliation mismatch должны запрещать новые входы.
- Holdout допускает только ingestion/completeness/gaps/duplicates/provenance/determinism.
- Количество тестов не фиксируется вручную: источники истины — discovery и CI.
- Fault-injection тесты подтверждают fail-closed поведение для каждого критического сбоя.
