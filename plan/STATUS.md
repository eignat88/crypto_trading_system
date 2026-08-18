# Статус проекта Crypto Trading System

## Текущий этап — 18.08.2026

Актуальный аудит и приоритеты разработки зафиксированы в
[`DEVELOPMENT_PLAN_2026-08-18.md`](DEVELOPMENT_PLAN_2026-08-18.md).

Проект находится на этапе backtest/walk-forward и закрытой независимой
валидации `Breakout Retest v2`. Проспективная выборка BTCUSDT/ETHUSDT 1h
накапливается с `2026-08-10` и остаётся закрытой для performance-метрик до
`2027-02-06T00:00:00Z`.

- ✅ Усилено ядро backtest и причинное исполнение N → N+1
- ✅ Добавлены версионирование derived-данных и fingerprint наборов
- ✅ Зафиксированы спецификация `Breakout Retest v2` и критерии независимой проверки
- ✅ Реализованы sealed health gate и инкрементальное обслуживание holdout
- ✅ Последний GitHub Actions run: unit, PostgreSQL 17 integration и Ruff — PASS
- ✅ Unit-тесты: **382 passed**
- 🚧 Paper trading заблокирован: базовые Paper Exchange, runtime и restart recovery
  реализованы, но не завершены composition root, единые миграции, reconciliation
  и эксплуатационные safety gates
- ⛔ Live trading заблокирован: paper execution реализован, но live order manager,
  exchange reconciliation и эксплуатационный monitoring не реализованы

## Выполненные задачи

### T1: Создание структуры проекта ✅
- Создана структура каталогов
- Настроен `pyproject.toml` с зависимостями
- Создан `.env.example` с конфигурацией
- Реализован модуль конфигурации `app/config/settings.py`
- Создан модуль подключения к БД `app/database/connection.py`
- Созданы SQL миграции для RAW слоя
- Реализован базовый клиент биржи `app/exchange/base_exchange.py`
- Реализован клиент Bybit `app/exchange/bybit_client.py`
- Реализован сборщик свечей `app/collectors/candle_collector.py`
- Создан скрипт загрузки истории `scripts/load_history.py`
- Создан `README.md` и `.gitignore`

### T2: Модуль индикаторов ✅
- EMA (Exponential Moving Average)
- RSI (Relative Strength Index)
- ATR (Average True Range)
- Волатильность (Historical Volatility, Bollinger Bands)
- Объём (Average Volume, Volume Ratio, OBV, VWAP)
- Цена (Price Change, Distance to EMA)

### T3: Определение режима рынка ✅
- MarketRegimeDetector с определением:
  - TREND_UP
  - TREND_DOWN
  - RANGE
  - HIGH_VOLATILITY

### T4: Backtest Engine ✅
- Модель комиссий (CommissionModel)
- Модель проскальзывания (SlippageModel)
- Виртуальный портфель (Portfolio)
- Движок бэктестинга (BacktestEngine)
- Типизированные контракты Signal, RiskDecision, Order, Fill, Position
- Журнал сигналов, risk-решений, ордеров и исполнений в BacktestResult
- Spot-only исполнение без short

### T5: Первая стратегия Trend DCA ✅
- Базовый класс стратегии (BaseStrategy)
- Стратегия Trend DCA с:
  - Условиями входа (close > EMA200, EMA50 > EMA200, RSI <= 45)
  - Условиями выхода (take-profit, trailing stop, смена режима)
  - DCA уровнями (3 safety orders)
- Базовый ордер и safety orders ограничены суммарно 10% капитала
- Уровень DCA изменяется только после фактического fill
- Trailing stop использует high-water mark свечей

### T6: Risk Engine ✅
- Проверки до открытия сделки:
  - Размер позиции
  - Exposure по активу
  - Загрузка капитала
  - Дневной/недельный лимит убытков
  - Просадка
  - Emergency stop
  - Устаревшие данные
- Автоматическая корректировка размера позиции
- Emergency stop механизм
- Проверка лимита 10% по итоговой позиции с учётом уже открытого объёма
- Risk-reducing spot-выход разрешён при emergency stop

### T11: Интеграция ядра backtest ✅
- `TrendDCAStrategy` подключается к `BacktestEngine` напрямую
- Поддержан источник индикаторов через свечу или `indicator_provider`
- Реализована цепочка `Signal → RiskDecision → Order → Fill → Portfolio`
- Добавлен сквозной тест base order + 3 DCA + закрытие

### T7: Коллектор индикаторов 🚧
- Реализован `app/collectors/indicator_collector.py` с расчётом и сохранением индикаторов
- Реализовано сохранение режима рынка в DDS
- Реализован инкрементальный расчёт недостающих versioned derived-строк для sealed holdout
- Общий автоматический запуск после каждой загрузки свечей ещё не подключён

### T8: DDS слой и RAW → DDS ETL ✅
- Добавлена схема DDS (`sql/002_create_dds.sql`)
- Добавлен идемпотентный ETL закрытых свечей (`sql/005_raw_to_dds_etl.sql`)
- Добавлены checkpoints, журнал запусков, карантин невалидных строк и проверки качества данных
- Добавлен CLI-загрузчик `scripts/load_dds.py`

### T10: MART слой 🚧
- Добавлена схема аналитических таблиц (`sql/003_create_mart.sql`)
- ETL-агрегации из DDS в MART ещё не реализованы

## Следующие шаги

1. Поддерживать sealed holdout без расчёта performance до даты разблокировки
2. Собрать существующие Paper Exchange и restart recovery в единый composition root
3. Добавить reconciliation, monitoring и fail-closed emergency stop
4. Завершить общий автоматический pipeline загрузка → DDS → indicators/regime
5. Реализовать агрегации DDS → MART

## Запуск тестов

```bash
# В Python 3.12 установить приложение и инструменты разработки
python -m pip install -e ".[dev]"

# Запустить тесты
pytest tests/

# Запустить с покрытием
pytest tests/ --cov=app --cov-report=html
```

Воспроизводимый baseline использует Python 3.12 (см. `.python-version` и CI).
Последний GitHub Actions run подтвердил **382 passed** для unit-тестов,
PostgreSQL 17 integration и Ruff correctness.

## Статус PostgreSQL Data Loading (обновлено 14.08.2026)

### Готовность к загрузке данных

- ✅ Исправлено вычисление `close_time` для всех 5 интервалов
- ✅ Unit-тесты проходят: 382 passed
- ✅ RAW → DDS ETL реализован и протестирован
- ✅ Интеграционные тесты подготовлены
- ✅ CI workflow `.github/workflows/ci.yml` включает job `PostgreSQL 17 integration`
- ✅ PostgreSQL 17 integration проходит в GitHub Actions
- 🔲 Требуется пилотная загрузка на целевой БД

**Статус:** CI-блокеры устранены. Массовая загрузка по-прежнему запрещена до
успешного пилота на целевой БД. Sealed holdout обслуживается отдельным
fail-closed pipeline без расчёта performance.

## Загрузка исторических данных

```bash
# Загрузить BTC и ETH за 3 года
python scripts/load_history.py --years 3

# Загрузить конкретный символ и интервал
python scripts/load_history.py --symbol BTCUSDT --interval 1d --years 2

# Продолжить загрузку с checkpoint
python scripts/load_history.py --resume
```
