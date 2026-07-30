# Crypto Trading System

Автоматизированная система торговли криптовалютами.

## Установка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd crypto_trading_system

# Создать виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows

# Установить зависимости
pip install -e ".[dev]"
```

## Конфигурация

```bash
# Скопировать пример конфигурации
cp .env.example .env

# Отредактировать .env
# - Указать DATABASE_URL
# - Указать API ключи биржи (опционально для paper trading)
```

Для `TRADING_MODE=live` используйте отдельный Bybit API-ключ с торговыми правами,
но **без права вывода средств**. Перед первым торговым запросом клиент проверяет права
ключа и отклоняет ключ, содержащий разрешение `Withdraw`.

## Запуск

```bash
# Проверить подключение к БД
python -m app.main

# Загрузить исторические данные
python scripts/load_history.py --symbol BTCUSDT --interval 1d --years 3
```

## Структура проекта

```
crypto_trading_system/
├── app/
│   ├── collectors/     # Сбор рыночных данных
│   ├── exchange/       # Клиенты бирж
│   ├── strategies/     # Торговые стратегии
│   ├── indicators/     # Технические индикаторы
│   ├── risk/           # Управление рисками
│   ├── execution/      # Исполнение ордеров
│   ├── backtest/       # Движок бэктестинга
│   ├── monitoring/     # Мониторинг
│   ├── reporting/      # Отчётность
│   ├── database/       # Подключение к БД
│   └── config/         # Конфигурация
├── sql/                # SQL миграции
├── tests/              # Тесты
├── scripts/            # Утилиты
└── docs/               # Документация
```

## Тестирование

```bash
pytest tests/
```

## Лицензия

MIT
