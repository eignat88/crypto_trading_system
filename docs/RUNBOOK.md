# Runbook: Crypto Trading System Paper Pilot

**Версия:** 21.08.2026
**Статус:** Операционный

---

## 1. Запуск

### Предусловия
- Python 3.12 установлен
- PostgreSQL доступна
- Миграции применены (`python scripts/migrate_database.py`)
- `.env` настроен

### Команда запуска

```powershell
cd D:\py_pro\crypto_trading_system
python scripts\run_paper_soak.py --duration-hours 10 --symbols BTCUSDT ETHUSDT
```

### Проверка после запуска
1. Логи: `runtime_state_changed from=CREATED to=RUNNING`
2. Логи: `paper_runtime_started trading_enabled=True`
3. Логи: `heartbeat_ok` каждые 30 сек
4. Логи: `pipeline_health=HEALTHY`

---

## 2. Остановка

### Graceful shutdown
```powershell
Ctrl+C  # или SIGTERM
```

### Проверка после остановки
1. Логи: `runtime_state_changed from=RUNNING to=STOPPED`
2. Логи: `checkpoint_saved`
3. Логи: `Graceful shutdown complete`

### Emergency stop (если нужно)
```python
# В коде:
await runtime.stop()
# Или:
await emergency_stop.activate(EmergencyReason.EMERGENCY_MANUAL_STOP, "operator decision")
```

---

## 3. Restart

### Когда нужен restart
- Обновление кода
- Смена конфигурации
- Crash recovery

### Процедура restart
1. Остановить текущий процесс (Ctrl+C)
2. Подождать 30 секунд
3. Запустить заново:
```powershell
python scripts\run_paper_soak.py --duration-hours 10 --symbols BTCUSDT ETHUSDT
```

### Проверка resume boundary
1. Логи: `state_restored sequence=N` (N > 0)
2. Логи: `duplicate_event_ignored` для уже обработанных свечей
3. Нет дублей order_id в `paper_orders`

---

## 4. Мониторинг

### Каждые 15 минут
- [ ] Heartbeat обновляется (`heartbeat_ok`)
- [ ] Pipeline health: `HEALTHY`
- [ ] Risk status: `OK`

### Каждый час
- [ ] Reconciliation: `fatal=0`
- [ ] Market data poll работает
- [ ] Нет ошибок в логах

### Каждый день
- [ ] Daily report сгенерирован (`artifacts/reports/daily_report_YYYY-MM-DD.json`)
- [ ] MART таблицы обновлены

---

## 5. Инциденты

### DB outage
**Симптомы:**
- `health_transition_critical reasons=('database: UNAVAILABLE',)`
- `EmergencyStop activated: EMERGENCY_DB_FAILURE`

**Действия:**
1. Проверить PostgreSQL: `python scripts\check_database.py`
2. Если БД недоступна — восстановить
3. Если БД доступна — перезапустить runtime
4. Проверить что `reconciliation_ok=True`

### Stale data
**Симптомы:**
- `market_data_stale`
- Risk engine блокирует сделки

**Действия:**
1. Проверить Bybit API: `python scripts\check_bybit_connection.py`
2. Проверить сетевое подключение
3. Дождаться восстановления потока данных

### Reconciliation fatal
**Симптомы:**
- `reconciliation_completed fatal=N`
- `risk_engine.update_reconciliation(False)`

**Действия:**
1. Проверить `paper_orders` и `paper_fills` в БД
2. Сравнить с runtime state
3. Если расхождение recoverable — игнорировать
4. Если fatal — остановить и расследовать

### Unknown order status
**Симптомы:**
- `UNKNOWN_ORDER_STATUS` в risk events
- Emergency stop активирован

**Действия:**
1. Проверить статус ордера в БД
2. Если ордер потерян — вручную обновить статус
3. Перезапустить runtime

---

## 6. Восстановление

### После DB outage
```powershell
# 1. Проверить БД
python scripts\check_database.py

# 2. Применить миграции если нужно
python scripts\migrate_database.py

# 3. Перезапустить
python scripts\run_paper_soak.py --duration-hours 10 --symbols BTCUSDT ETHUSDT
```

### После crash
```powershell
# Runtime автоматически восстановит state из checkpoint
python scripts\run_paper_soak.py --duration-hours 10 --symbols BTCUSDT ETHUSDT
```

### После corruption
```powershell
# 1. Остановить runtime
# 2. Проверить целостность данных
python scripts\check_database.py

# 3. Если данные повреждены — восстановить из backup
# 4. Перезапустить
```

---

## 7. Расписание (Windows Task Scheduler)

### Установка
```powershell
cd D:\py_pro\crypto_trading_system
.\scripts\install_paper_runtime_task.ps1
```

### Проверка
```powershell
Get-ScheduledTask -TaskName "Crypto Trading Paper Runtime"
```

### Ручной запуск
```powershell
Start-ScheduledTask -TaskName "Crypto Trading Paper Runtime"
```

### Остановка
```powershell
Stop-ScheduledTask -TaskName "Crypto Trading Paper Runtime"
```

---

## 8. Контакты

- **Проект:** `D:\py_pro\crypto_trading_system`
- **Логи:** `D:\py_pro\crypto_trading_system\logs\`
- **Отчёты:** `D:\py_pro\crypto_trading_system\artifacts\`
- **Миграции:** `D:\py_pro\crypto_trading_system\database\migrations\`

---

## 9. Полезные команды

```powershell
# Проверка БД
python scripts\check_database.py

# Проверка Bybit
python scripts\check_bybit_connection.py

# Smoke test
python scripts\smoke_test.py --duration 1

# Soak test
python scripts\run_paper_soak.py --duration-hours 4 --symbols BTCUSDT ETHUSDT

# MART ETL
python scripts\load_mart.py

# Unit tests
python -m pytest tests/unit -q

# Lint
python -m ruff check . --select F --ignore F401,F841
```
