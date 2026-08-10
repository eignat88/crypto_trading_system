# Диагностика готовности к полной исторической загрузке

Скопируйте файлы с сохранением каталогов в корень:

```text
D:\py_pro\crypto_trading_system
├── scripts\diagnose_readiness.ps1
├── scripts\diagnose_readiness.py
└── sql\diagnostic_readiness.sql
```

Скрипт никогда не запускает `load_history.py`.

## 1. Безопасная диагностика без изменений

```powershell
cd "D:\py_pro\crypto_trading_system"

powershell.exe -ExecutionPolicy Bypass `
    -File .\scripts\diagnose_readiness.ps1 `
    -Symbol BTCUSDT `
    -Interval 1h
```

В этом режиме миграции, тесты и `RAW -> DDS` не запускаются. Поэтому итоговое решение будет
`blocked`, пока активные проверки не будут подтверждены.

## 2. Полная проверка критерия готовности

Интеграционные тесты запускаются только при наличии отдельной тестовой БД. Имя базы в
`TEST_DATABASE_URL` обязано содержать `test`; иначе тесты будут безопасно заблокированы.

Пример для текущего окна PowerShell:

```powershell
$env:TEST_DATABASE_URL = "postgresql://crypto_test:CHANGE_ME@localhost:5432/crypto_trading_test"

powershell.exe -ExecutionPolicy Bypass `
    -File .\scripts\diagnose_readiness.ps1 `
    -Symbol BTCUSDT `
    -Interval 1h `
    -RunActiveChecks
```

Не помещайте настоящий пароль в файл или Git. Задайте переменную окружения только локально.

Активный режим последовательно:

1. применяет миграции дважды;
2. запускает `pytest -m integration -q` только против тестовой БД;
3. запускает `RAW -> DDS` дважды;
4. проверяет RAW, журналы, checkpoint и события качества;
5. читает последний завершённый workflow `ci.yml` через `gh`;
6. формирует итоговый CSV.

## Результат

Файлы создаются только в:

```text
D:\py_pro\crypto_trading_system\logs\readiness_bybit_BTCUSDT_1h_YYYYMMDD_HHMMSS
```

Главный файл:

```text
readiness_summary.csv
```

CSV имеет разделитель `;` и кодировку UTF-8 BOM, поэтому корректно открывается в Excel.

Решение находится в строке:

```text
category=decision; check_name=full_history_load
```

- `status=success` — все обязательные критерии подтверждены;
- `status=blocked` — полную трёхлетнюю загрузку начинать нельзя.

При `blocked` откройте указанный в `evidence_file` лог и проверьте:

- `raw_system.loading_journal`;
- `dds.etl_run`;
- `dds.etl_checkpoint`;
- `dds.data_quality_event`.

Не запускайте трёхлетнюю загрузку повторно целиком для устранения диагностического расхождения.
