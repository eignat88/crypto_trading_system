# Статус проекта Crypto Trading System

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

### T5: Первая стратегия Trend DCA ✅
- Базовый класс стратегии (BaseStrategy)
- Стратегия Trend DCA с:
  - Условиями входа (close > EMA200, EMA50 > EMA200, RSI <= 45)
  - Условиями выхода (take-profit, trailing stop, смена режима)
  - DCA уровнями (3 safety orders)

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

### T7: Коллектор индикаторов 🚧
- Реализован `app/collectors/indicator_collector.py` с расчётом и сохранением индикаторов
- Реализовано сохранение режима рынка в DDS
- Автоматический запуск после загрузки свечей и инкрементальный пересчёт ещё не подключены

### T8: DDS слой и RAW → DDS ETL ✅
- Добавлена схема DDS (`sql/002_create_dds.sql`)
- Добавлен идемпотентный ETL закрытых свечей (`sql/005_raw_to_dds_etl.sql`)
- Добавлены checkpoints, журнал запусков, карантин невалидных строк и проверки качества данных
- Добавлен CLI-загрузчик `scripts/load_dds.py`

### T10: MART слой 🚧
- Добавлена схема аналитических таблиц (`sql/003_create_mart.sql`)
- ETL-агрегации из DDS в MART ещё не реализованы

## Следующие шаги

1. Завершить автоматическую интеграцию коллектора индикаторов с загрузкой свечей
2. Реализовать агрегации DDS → MART
3. **T11–T13**: Интеграция стратегии, walk-forward и оценка
4. **T15**: Paper Trading модуль
5. **T26**: Мониторинг и уведомления

## Запуск тестов

```bash
# Установить зависимости
pip install -e ".[dev]"

# Запустить тесты
pytest tests/

# Запустить с покрытием
pytest tests/ --cov=app --cov-report=html
```

## Загрузка исторических данных

```bash
# Загрузить BTC и ETH за 3 года
python scripts/load_history.py --years 3

# Загрузить конкретный символ и интервал
python scripts/load_history.py --symbol BTCUSDT --interval 1d --years 2

# Продолжить загрузку с checkpoint
python scripts/load_history.py --resume
```
