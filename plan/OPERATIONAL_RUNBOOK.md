# Операционный runbook: от smoke soak до live pilot

**Дата:** 21.08.2026
**Проект:** crypto_trading_system
**Цель:** последовательно пройти 6 этапов от короткого прогона до 90-дневного paper pilot

---

## Общие принципы

1. **Каждый этап — gate.** Следующий этап начинается ТОЛЬКО после успешного прохождения предыдущего.
2. **Fail-closed.** Любая критическая ошибка = остановка, расследование, исправление, повтор.
3. **Доказательства.** Каждый этап фиксируется в JSON-отчёте и БД.
4. **Без изменений стратегии.** Во время pilot запрещено менять strategy/version/parameters.

---

## Этап 1: Smoke soak (короткий прогон, 1–4 часа)

### Цель
Убедиться, что paper runtime запускается, обрабатывает свечи, чекпоинтится и корректно завершается на реальных данных.

### Предусловия
- PostgreSQL 17 запущена и доступна
- Миграции применены (`python scripts/migrate_database.py`)
- Bybit API доступен (demo/testnet)
- `.env` настроен

### Последовательность действий

```bash
# 1. Проверить подключение к БД
python scripts/check_database.py

# 2. Проверить подключение к Bybit
python scripts/check_bybit_connection.py

# 3. Запустить smoke soak на 1–4 часа
TRADING_MODE=paper python scripts/run_paper_soak.py \
  --duration-hours 4 \
  --symbols BTCUSDT ETHUSDT \
  --output-report artifacts/smoke_soak_report.json
```

### Что проверять во время прогона
- [ ] Логи: нет ошибок подключения к БД
- [ ] Логи: свечи обрабатываются (candle_processed)
- [ ] Логи: checkpoint сохраняется
- [ ] Логи: heartbeat обновляется
- [ ] Логи: HealthCoordinator проверяет health
- [ ] Логи: PaperReconciler не находит fatal discrepancies

### Критерии успеха
- [ ] Runtime запустился без ошибок
- [ ] Обработано ≥ 1 закрытая свеча
- [ ] Checkpoint сохранился в БД
- [ ] Heartbeat записан в `monitoring.runtime_health`
- [ ] Нет duplicate order_id в `paper_orders`
- [ ] Нет fatal reconciliation discrepancies
- [ ] Runtime корректно завершился по таймеру

### Если провалилось
1. Проверить логи в `logs/`
2. Проверить подключение к БД и Bybit
3. Исправить проблему
4. Повторить smoke soak

---

## Этап 2: 24–72ч soak с restart

### Цель
Доказать стабильность runtime на протяжении 24–72 часов, включая управляемый restart.

### Предусловия
- Этап 1 пройден успешно
- Сервер/машина стабильна (не перезагружается)
- Достаточно дискового пространства для логов

### Последовательность действий

```bash
# 1. Запустить long-running soak
TRADING_MODE=paper python scripts/run_paper_soak.py \
  --duration-hours 72 \
  --symbols BTCUSDT ETHUSDT \
  --output-report artifacts/long_soak_report.json

# 2. Через 24 часа — выполнить restart
#    Остановить текущий process (Ctrl+C или SIGTERM)
#    Подождать 30 секунд
#    Запустить заново с теми же параметрами

# 3. После restart — проверить resume
#    Логи: "state_restored" с ненулевым sequence
#    Логи: "duplicate_event_ignored" для уже обработанных свечей
#    Логи: нет дублей order_id

# 4. Дождаться завершения 72ч
```

### Что проверять каждые 24 часа
- [ ] Market data поступает (candle_processed > 0)
- [ ] Sequence монотонно возрастает
- [ ] Checkpoint freshness < 5 минут
- [ ] Heartbeat обновляется
- [ ] Нет duplicate orders
- [ ] PnL считается корректно
- [ ] Reconciliation: нет fatal discrepancies

### Что проверять после restart
- [ ] `state_restored` с sequence > 0
- [ ] Runtime продолжает обрабатывать свечи
- [ ] Нет повторных ордеров (idempotency)
- [ ] Позиции восстановлены из БД
- [ ] Cash balance совпадает с checkpoint

### Критерии успеха
- [ ] 72 часа без критических ошибок
- [ ] Restart выполнен успешно (resume boundary работает)
- [ ] Монотонный sequence на протяжении всего прогона
- [ ] Нет duplicate order_id после restart
- [ ] Market throughput > 0 (свечи обрабатываются)
- [ ] JSON-отчёт сохранён и валиден

### Если провалилось
1. Проанализировать отчёт `artifacts/long_soak_report.json`
2. Найти точку отказа в логах
3. Исправить проблему
4. Начать soak заново (с нуля)

---

## Этап 3: Проверка Windows scheduled task

### Цель
Убедиться, что paper runtime корректно запускается и останавливается по расписанию через Windows Task Scheduler.

### Предусловия
- Этап 2 пройден успешно
- Windows 10/11 с PowerShell
- Python доступен в PATH

### Последовательность действий

```powershell
# 1. Установить scheduled task (одноразово)
#    Открыть PowerShell от администратора
#    Запустить скрипт установки из scripts/

# 2. Проверить что task создался
Get-ScheduledTask -TaskName "CryptoTradingPaper*"

# 3. Запустить task вручную для проверки
Start-ScheduledTask -TaskName "CryptoTradingPaperStart"

# 4. Подождать 1–2 часа, проверить логи

# 5. Остановить task
Stop-ScheduledTask -TaskName "CryptoTradingPaperStop"

# 6. Проверить что runtime корректно завершился
```

### Что проверять
- [ ] Task запускается в указанное время
- [ ] Runtime стартует и обрабатывает свечи
- [ ] Task останавливается в указанное время
- [ ] Runtime корректно завершается (graceful shutdown)
- [ ] Checkpoint сохраняется перед остановкой
- [ ] Нет "зависших" процессов после остановки

### Критерии успеха
- [ ] Task запускается по расписанию 3 дня подряд
- [ ] Runtime работает в пределах торгового окна
- [ ] Runtime не работает вне торгового окна
- [ ] Graceful shutdown при остановке
- [ ] Нет orphan processes

---

## Этап 4: Подключение cron/scheduler для MART ETL

**Статус:** обёртка `scripts/run_daily_mart_report.ps1` подготовлена; установка
расписания и семидневное evidence на целевом хосте не выполнены.

### Цель
Настроить автоматический запуск MART ETL и генерацию immutable daily report.

### Предусловия
- Этап 2 пройден успешно
- `mart` schema существует в PostgreSQL
- DailyReportGenerator работает (тесты проходят)

### Последовательность действий

```powershell
# 1. Проверить ручной последовательный запуск MART ETL и daily report
.\scripts\run_daily_mart_report.ps1

# 2. Настроить расписание (cron или Task Scheduler)
#    MART ETL: ежедневно в 00:05 UTC (после закрытия дня)
#    Daily report: ежедневно в 00:10 UTC

# 3. Проверить что отчёты генерируются
Get-ChildItem artifacts\reports\daily_report_*.json

# 4. Проверить что MART таблицы обновляются
#    SELECT count(*) FROM mart.daily_performance;
#    SELECT count(*) FROM mart.trade_statistics;
```

### Что проверять
- [ ] MART ETL запускается по расписанию
- [ ] `mart.daily_performance` обновляется
- [ ] `mart.trade_statistics` обновляется
- [ ] `mart.drawdown_history` обновляется
- [ ] `mart.monthly_returns` обновляется
- [ ] Daily report генерируется
- [ ] Content hash детерминирован

### Критерии успеха
- [ ] 7 дней подряд MART ETL запускается без ошибок
- [ ] Daily report генерируется каждый день
- [ ] Данные в MART консистентны с DDS

---

## Этап 5: Runbook

**Статус:** базовый операторский runbook создан в `docs/RUNBOOK.md`; остаются
operator walkthrough, контакты/escalation path и утверждение процедуры снятия stop.

### Цель
Подготовить документацию для оператора: запуск, остановка, восстановление, расследование инцидентов.

### Структура runbook

```markdown
# Runbook: Crypto Trading System Paper Pilot

## 1. Запуск
- Предусловия
- Команда запуска
- Проверка после запуска

## 2. Остановка
- Graceful shutdown (Ctrl+C / SIGTERM)
- Emergency stop (если нужно)
- Проверка после остановки

## 3. Restart
- Когда cần restart
- Процедура restart
- Проверка resume boundary

## 4. Мониторинг
- Каждые 15 минут: heartbeat, sequence, candle lag
- Каждый час: reconciliation, PnL, drawdown
- Каждый день: daily report, MART data

## 5. Инциденты
- DB outage → EmergencyStop → Recovery
- Stale data → RiskEngine blocks → Fix source
- Reconciliation fatal → Block trades → Investigate
- Unknown order status → EmergencyStop → Manual check

## 6. Восстановление
- После DB outage
- После restart
- После corruption

## 7. Контакты
- Ответственные
- escalation path
```

### Критерии успеха
- [ ] Runbook написан и проверен
- [ ] Оператор может выполнить каждый пункт без подсказок
- [ ] Runbook хранится в `docs/` или `plan/`

---

## Этап 6: 90-дневный paper pilot

### Цель
Накопить достаточно данных для решения о live trading.

### Предусловия
- Этапы 1–5 пройдены успешно
- Зафиксированы: strategy/version, universe, capital, risk limits, SLO

### Фиксация конфигурации

```markdown
## Pilot Configuration (зафиксировать до начала)

- Strategy: Trend DCA v1 (или другой кандидат)
- Symbols: BTCUSDT, ETHUSDT
- Interval: 1h
- Initial capital: 500 USDT
- Max risk per trade: 0.5%
- Max position size: 10%
- Max drawdown: 10%
- Trading window: TBD
- Owner: TBD
```

### Последовательность действий

```
День 1–7:   Burn-in (наблюдаемый, без изменений)
День 8–90:  Основной paper period
Еженедельно: Проверка availability, gaps, reconciliation, drawdown
```

### Paper acceptance gates (все должны быть выполнены)

| Gate | Требование |
|---|---|
| Duration | ≥ 90 календарных дней |
| Trades | ≥ 100 закрытых сделок |
| Reconciliation | 0 необъяснённых failures |
| Duplicate orders | 0 после restart |
| Alerts | 100% критических инцидентов с alert + audit trail |
| PnL | Положительный net PnL после costs |
| Drawdown | Не превышает утверждённый risk limit |
| Symbols | Результаты не зависят от одного символа |

### Еженедельная проверка

```markdown
## Weekly Check (каждый понедельник)

1. Availability: runtime uptime, data gaps
2. Reconciliation: fatal discrepancies за неделю
3. Drawdown: текущий vs лимит
4. Incidents: количество и типы
5. PnL: weekly net, cumulative
6. Trades: количество, win rate
7. Decisions: были ли изменения стратегии (запрещено)
```

### Если gate не пройден
1. Документировать причину
2. Определить: infrastructure issue или strategy issue
3. Infrastructure → исправить, начать заново
4. Strategy → зафиксировать, начать новый период

### Критерии завершения pilot
- [ ] Все gates пройдены
- [ ] Report сгенерирован и зафиксирован
- [ ] Решение о live: go / no-go (отдельное совещание)

---

## Порядок выполнения (сводка)

```
Этап 1: Smoke soak (1–4ч)           → Gate: smoke passed
    ↓
Этап 2: 24–72ч soak + restart       → Gate: long soak passed
    ↓
Этап 3: Windows scheduled task       → Gate: scheduler works
    ↓
Этап 4: MART ETL + daily report      → Gate: reports generate
    ↓
Этап 5: Runbook                      → Gate: operator can run
    ↓
Этап 6: 90-дневный paper pilot       → Gate: all acceptance criteria
    ↓
Live design review (отдельное решение)
```

---

## Контрольный чеклист перед каждым этапом

- [ ] Python 3.12, зависимости установлены
- [ ] PostgreSQL доступна, миграции применены
- [ ] `.env` настроен (не содержит секретов в коде)
- [ ] Bybit API доступен
- [ ] Все тесты проходят (`pytest tests/unit -q`)
- [ ] Предыдущий этап завершён успешно
