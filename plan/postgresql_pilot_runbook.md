# Пилотная проверка загрузки PostgreSQL

Этот регламент закрывает этапы 1–5 из `postgresql_data_loading_plan.md` на одном
контрольном диапазоне. Диапазон всегда трактуется как полуинтервал `[start, end)`.

## 0. Воспроизводимый baseline

Локальные проверки и CI выполняются на Python 3.12. Из чистого checkout до работы
с БД необходимо установить тот же набор зависимостей и выполнить проверки:

```bash
python --version  # ожидается Python 3.12.x
python -m pip install -e ".[dev]"
python -m ruff check . --select F --ignore F401,F841
python -m pytest tests/unit -q
```

PostgreSQL integration baseline использует PostgreSQL 17. Для изолированной
тестовой БД команда приведена в разделе 5. Tracked backup-файлы и секреты не
должны добавляться в репозиторий; секреты задаются только через локальный `.env`.

## 1. Безопасные условия запуска

- PostgreSQL 17 доступен;
- `TRADING_MODE=paper`;
- `DATABASE_URL` и `DATABASE_URL_SYNC` заданы только в локальном `.env`;
- API-ключ для публичных свечей не требуется;
- перед пилотом не удаляются уже загруженные свечи;
- при ошибке повторная полная загрузка не запускается до проверки журналов.

## 2. Применение миграций

```powershell
python .\scripts\apply_migrations.py
python .\scripts\apply_migrations.py
```

Оба запуска должны завершиться строкой `migration_status=success`. Второй запуск
подтверждает повторяемость DDL без удаления данных.

## 3. Пилот API → RAW

```powershell
python .\scripts\load_history.py `
    --symbol BTCUSDT `
    --interval 1h `
    --start 2026-07-01 `
    --end 2026-07-08
```

Ожидаемый диапазон: 168 часовых свечей, от `2026-07-01 00:00:00 UTC` включительно
до `2026-07-08 00:00:00 UTC` исключительно.

Проверка RAW:

```powershell
python .\scripts\verify_market_data.py `
    --symbol BTCUSDT `
    --interval 1h `
    --start 2026-07-01T00:00:00Z `
    --end 2026-07-08T00:00:00Z `
    --layer raw
```

Свеча с `open_time = 2026-07-08 00:00:00 UTC`, если она уже существует в RAW,
не удаляется и не влияет на проверку указанного полуинтервала.

## 4. Пилот RAW → DDS и повторный запуск

```powershell
python .\scripts\load_dds.py --exchange bybit --symbol BTCUSDT --interval 1h
python .\scripts\load_dds.py --exchange bybit --symbol BTCUSDT --interval 1h
```

На первом запуске ожидаются закрытые свечи в `inserted`. На втором запуске при
неизменившемся RAW ожидается `inserted=0`; дубли появиться не должны.

Итоговая проверка:

```powershell
python .\scripts\verify_market_data.py `
    --symbol BTCUSDT `
    --interval 1h `
    --start 2026-07-01T00:00:00Z `
    --end 2026-07-08T00:00:00Z `
    --layer all
```

Код возврата `0` и `status=success` означают, что в диапазоне:

- RAW и DDS содержат по 168 свечей;
- пропусков нет;
- некорректных свечей и событий качества нет;
- существует успешный запуск DDS ETL и checkpoint.

## 5. Интеграционная проверка PostgreSQL

Для отдельной тестовой БД:

```powershell
$env:TEST_DATABASE_URL = "postgresql://crypto_test:LOCAL_PASSWORD@localhost:5432/crypto_trading_test"
python -m pytest -m integration -q
```

Тест удаляет проектные схемы в указанной тестовой БД. Нельзя направлять
`TEST_DATABASE_URL` на рабочую БД с историей.

В GitHub Actions этот тест выполняется автоматически на временном PostgreSQL 17.

## 6. Решение о следующем этапе

Полную историческую загрузку можно начинать только когда одновременно выполнено:

- миграции дважды применились без ошибок;
- интеграционные тесты прошли;
- RAW-проверка завершилась успешно;
- первый и повторный RAW → DDS запуск объяснимы;
- итоговая проверка вернула `status=success`;
- в CI успешно завершились Ruff, unit tests и PostgreSQL 17 integration.

При любом расхождении остановить поток, сохранить вывод команд и проверить
`raw_system.loading_journal`, `dds.etl_run`, `dds.etl_checkpoint` и
`dds.data_quality_event`. Не перезапускать трёхлетнюю загрузку целиком.
