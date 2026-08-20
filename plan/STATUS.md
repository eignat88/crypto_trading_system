# Статус проекта Crypto Trading System

## Текущий срез — 20.08.2026

Исследовательский и paper foundation реализованы. Текущий этап — не «сборка
composition root», а **стендовая валидация непрерывного paper runtime**, интеграция
мониторинга/emergency stop и reconciliation. Sealed holdout `Breakout Retest v2`
для BTCUSDT/ETHUSDT 1h остаётся закрытым для performance до
`2027-02-06T00:00:00Z` и выполнения sample gate.

## Матрица готовности

| Контур | Статус | Подтверждено в коде | Открытый gate |
|---|---|---|---|
| Python/CI | ✅ | Python 3.12, Ruff correctness, unit и PostgreSQL 17 jobs | Поддерживать CI |
| Data pipelines | ✅ Код готов | RAW/DDS quality/checkpoints, derived pipeline, MART ETL | Целевой PostgreSQL pilot и расписание |
| Backtest/strategies/risk | ✅ Ядро готово | Causal execution, costs, walk-forward, frozen v2, Risk Engine | Зафиксировать pilot candidate |
| Sealed holdout | 🚧 Накопление | Fail-closed update, health и preflight | Только технические проверки до unlock |
| Paper application | ✅ Код готов | CLI, preflight, restore, Bybit REST bootstrap/polling, warmup, managed pipeline, checkpoint, shutdown | Проверить production feed коротким стендовым soak |
| Restart/idempotency | ✅ Тестовый baseline | PostgreSQL E2E для sequence, orders/fills, PnL restore; duplicate-order guard | Управляемый restart во время soak |
| Monitoring | 🚧 Foundation готов | Durable heartbeat, DB/market/pipeline/risk monitors, console notifier | Runtime wiring, watchdog и alert transport |
| Emergency stop | 🚧 Primitive готов | Идемпотентная последовательность disable/close/checkpoint/audit/notify/stop | Автоматические triggers и fault injection |
| Soak validation | 🚧 Runner готов | Bounded CLI, samples, lifecycle evidence, JSON report | 24–72 часа с живыми событиями |
| Reconciliation | ❌ Не реализовано | Отдельного operational reconciler нет | До любого paper pilot |
| Live execution | ⛔ Запрещено | Live mode отклоняется | Только отдельный go/no-go после pilot gates |

## Важные ограничения текущей реализации

1. `build_paper_dependencies()` использует long-running Bybit REST → RAW → DDS
   источник закрытых 1h свечей. Статический `PaperMarketData` сохранён только для
   детерминированных тестов; production-поток требует стендовой проверки с PostgreSQL.
2. Health monitors и `EmergencyStop` существуют как компоненты, но ещё не образуют
   единый автоматический watchdog в основном runtime.
3. Soak runner сохраняет heartbeat и JSON evidence, однако сам по себе не доказывает
   market throughput, restart и отсутствие дублей: это проверяется по отчёту и БД.
4. Console notifier не является внешним alert routing.
5. Reconciliation orders/fills/positions/equity/last event отсутствует; live запрещён.
6. Предыдущие короткие `restart_before`/`restart_after` с sequence=0 не являются
   доказательством отказа: restart/idempotency остаётся проверить на событии X с
   ненулевым durable checkpoint. Реализовано, требуется проверка.

## Следующие задачи по порядку

1. Выполнить короткий smoke soak long-running closed-candle source.
2. Связать DB/market/pipeline/risk monitors с emergency stop и внешним notifier.
3. Провести fault-injection и короткий smoke soak, затем 24–72-часовой стендовый soak.
4. Во время soak выполнить restart и подтвердить monotonic sequence, checkpoint и
   отсутствие duplicate `client_order_id`.
5. Реализовать operational reconciliation до разрешения новых входов.
6. Подключить расписание MART и immutable daily report.
7. Выполнить целевой PostgreSQL data pilot и зафиксировать pilot configuration/SLO.

## Воспроизводимые проверки

```bash
python --version
python -m ruff check . --select F --ignore F401,F841
python -m pytest tests/unit -q
python -m pytest tests/reporting -q
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
