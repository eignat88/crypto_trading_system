# Статус проекта Crypto Trading System

## Текущий этап — 20.08.2026

Актуальные приоритеты и критерии выхода зафиксированы в
[`DEVELOPMENT_PLAN_2026-08-19.md`](DEVELOPMENT_PLAN_2026-08-19.md).

Проект находится на этапе сборки единого **paper runtime** и накопления sealed
independent holdout `Breakout Retest v2`. Holdout BTCUSDT/ETHUSDT 1h накапливается
с `2026-08-10`; performance остаётся закрытым до `2027-02-06T00:00:00Z` и до
выполнения требований к полноте выборки.

## Сводка готовности

| Контур | Статус | Что подтверждено | Следующий gate |
|---|---|---|---|
| Python/CI baseline | ✅ Готово | Python 3.12, Ruff correctness, unit и PostgreSQL 17 jobs | Поддерживать зелёный CI |
| RAW → DDS | ✅ Готово | Идемпотентный ETL, quality quarantine, checkpoints | Пилот на целевой PostgreSQL |
| Indicators/regime | ✅ Готово | Managed closed-candle pipeline, readiness и fail-closed gate | Провести PostgreSQL soak |
| DDS → MART | ✅ Код готов | Идемпотентные daily/trade/drawdown/monthly агрегаты | Расписание и immutable daily report |
| Миграции | ✅ Готово | Канонический каталог, checksum journal, repeat-safe runner | Проверять upgrade path при новых DDL |
| Backtest/walk-forward | ✅ Ядро готово | N → N+1, costs, portfolio, audit trail | Утвердить pilot strategy |
| Sealed holdout | 🚧 Накопление | Fail-closed update, health и preflight | Не открывать performance до unlock gate |
| Paper execution | ✅ Composition root готов | Preflight, restore, RiskEngine, warmup, lifecycle, checkpoint и signal shutdown | Подключить long-running feed и провести restart E2E на PostgreSQL |
| Monitoring/reconciliation | 🚧 Частично | Метрики и reporting-компоненты | Alerts, heartbeat, emergency stop, reconciliation |
| Live execution | ⛔ Запрещено | Реального order manager нет | Только отдельный go/no-go после paper gates |

## Изменения, учтённые в этом обновлении

- Единый migration contract расположен в `database/migrations/`; штатная команда —
  `python scripts/migrate_database.py`. Применённые версии и SHA-256 checksums
  записываются в `public.schema_migrations`.
- `MarketDataPipeline` объединяет RAW → DDS и инкрементальный расчёт
  indicators/regime; его библиотечная композиция готова, операционный scheduler — нет.
- Managed pipeline integration suite подтверждает полный closed-candle flow, durable
  restart с восстановлением sequence/position/PnL и запрет стратегии до EMA200 warmup.
- DDS → MART ETL реализует идемпотентное заполнение `daily_performance`,
  `trade_statistics`, `drawdown_history` и `monthly_returns`.
- Paper persistence включает orders, fills, positions, runtime/recovery state и PnL
  snapshots. Это не означает готовность paper-приложения к длительному запуску.

## Ближайшие задачи

1. Подключить long-running closed-candle feed к готовому composition root и провести
   24-часовой soak.
2. Расширить restart/idempotency E2E вокруг signal, order, fill и PnL snapshot на PostgreSQL.
3. Провести soak managed market pipeline и фонового MART ETL на целевой БД.
4. Реализовать heartbeat, alert routing и fail-closed emergency stop.
5. Реализовать reconciliation orders/fills/positions/equity/last market event.
6. Провести целевой PostgreSQL pilot по `postgresql_pilot_runbook.md`.
7. Зафиксировать pilot strategy, risk limits, SLO, hosting и полномочия снятия stop.

## Воспроизводимые проверки

```bash
python --version
python -m pip install -e ".[dev]"
python -m ruff check . --select F --ignore F401,F841
python -m pytest tests/unit -q
```

PostgreSQL integration suite запускается только с изолированной тестовой БД:

```bash
python scripts/migrate_database.py --database-url "$TEST_DATABASE_SQLALCHEMY_URL"
python -m pytest -m integration -q
```

Количество тестов намеренно не фиксируется в статусе: источником истины является
текущий test discovery и результат CI, а не вручную обновляемое число.

## Safety gates

- `TRADING_MODE=live` запрещён до отдельного решения после минимум 90 дней и 100
  закрытых paper-сделок.
- Потеря БД, stale data, recovery/reconciliation mismatch или risk breach должны
  блокировать новые входы.
- Holdout разрешает только ingestion, completeness/gap/duplicate, provenance,
  reconciliation и determinism checks; backtest/PnL/attribution запрещены.
- Grid, ML, leverage, short и futures не входят в текущий MVP.
