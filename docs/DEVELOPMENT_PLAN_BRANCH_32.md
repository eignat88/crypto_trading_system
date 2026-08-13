# План разработки ветки 32

## Анализ текущего состояния

На текущем этапе проект находится в фазе подготовки к безопасному paper trading.

Реализовано:

- структура модулей collectors, exchange, indicators, strategies, risk, execution, backtest, monitoring, reporting;
- получение рыночных данных Bybit;
- RAW → DDS поток данных;
- нормализованные свечи и индикаторы;
- backtest engine;
- комиссии и slippage models;
- walk-forward validation;
- Risk Engine базового уровня;
- CI и тестовый контур.

Не реализовано:

- Paper Exchange;
- восстановление состояния после рестарта;
- полноценное хранение paper балансов, позиций и ордеров;
- reconciliation с биржей;
- emergency stop;
- production monitoring.

## Цель ветки 32

Подготовить устойчивый контур Paper Trading без возможности отправки реальных ордеров.

Главный критерий успеха: после запуска система должна безопасно работать с реальными котировками, виртуальным капиталом и полностью восстанавливать состояние после остановки.

## Этап 1. Paper Exchange Core

Создать модуль:

```
app/execution/paper_exchange/
```

Функции:

- виртуальное исполнение BUY/SELL;
- поддержка market и limit ордеров;
- комиссии;
- slippage;
- частичные исполнения;
- статусы ордеров.

Добавить сущности:

- PaperOrder;
- PaperExecution;
- PaperPosition;
- PaperBalance.

## Этап 2. Persistence

Добавить PostgreSQL таблицы DDS:

- paper_orders;
- paper_executions;
- paper_positions;
- paper_balances;
- paper_state_checkpoint.

Требования:

- UTC timestamptz;
- уникальный client_order_id;
- идемпотентная запись;
- восстановление после рестарта.

## Этап 3. Интеграция цепочки исполнения

Фиксируем поток:

Market Data
→ Indicators
→ Market Regime
→ Strategy Signal
→ Risk Engine
→ Paper Exchange
→ Persistence
→ Reporting

Стратегии не должны иметь доступа к Exchange.

## Этап 4. Risk Engine усиление

Добавить проверки:

- актуальность данных;
- доступность БД;
- emergency stop flag;
- лимиты капитала;
- дневной/недельный убыток;
- максимальная просадка.

Каждое решение сохранять:

- decision code;
- reason;
- timestamp;
- strategy version.

## Этап 5. Monitoring

Добавить контроль:

- heartbeat сервиса;
- ошибки API;
- задержки данных;
- состояние позиции;
- расхождения состояния.

## Этап 6. Тестирование

Добавить тесты:

Unit:

- расчёт исполнения;
- комиссии;
- slippage;
- восстановление состояния;
- Risk Engine decisions.

Integration:

- полный цикл Signal → Risk → Paper Exchange;
- restart recovery;
- duplicate order protection.

## Что не делать в ветке 32

Запрещено:

- live trading;
- реальные API ключи с торговыми правами;
- увеличение капитала;
- новые стратегии;
- ML оптимизация;
- фьючерсы и плечо.

## Критерии готовности ветки

1. Paper Trading запускается на реальных котировках.
2. Баланс и позиции сохраняются после перезапуска.
3. Повторный запуск не создаёт дубли ордеров.
4. Все действия имеют журналирование.
5. Risk Engine может заблокировать сделку.
6. Backtest и Paper Trading используют единый формат сигналов.

## Следующий шаг после ветки 32

После успешного завершения:

1. накопление статистики paper trading;
2. reconciliation;
3. emergency stop сценарии;
4. только после выполнения критериев — подготовка live режима.
