# Роадмэп Crypto Trading System

**Срез:** 19.08.2026.
**Источник текущих приоритетов:** [`DEVELOPMENT_PLAN_2026-08-19.md`](DEVELOPMENT_PLAN_2026-08-19.md).
**Текущий milestone:** воспроизводимый fail-closed paper runtime. Live trading заблокирован.

## Выполненный foundation

- [x] Python 3.12 local/CI baseline и PostgreSQL 17 integration job.
- [x] RAW → DDS ETL: closed candles, quality events, checkpoints, run journal.
- [x] Versioned indicators/regime и инкрементальный market pipeline.
- [x] Идемпотентный DDS → MART ETL для daily, trade, drawdown и monthly metrics.
- [x] Backtest/walk-forward foundation с причинным исполнением и audit trail.
- [x] Trend DCA, Breakout Retest и frozen Breakout Retest v2 specification.
- [x] Risk Engine и persistent risk state.
- [x] Paper exchange, fill simulation, execution runtime и PostgreSQL repositories.
- [x] Paper restart state и persistent PnL snapshots.
- [x] Канонические checksum-protected PostgreSQL migrations.
- [x] Sealed holdout ingestion/health/preflight pipeline.

## Milestone M1 — runnable paper application (P0)

- [ ] Добавить единственный composition root/CLI.
- [ ] Выполнять startup preflight и проверку версии схемы.
- [ ] Восстанавливать runtime, risk, orders, fills, positions и PnL state.
- [ ] Делать warmup и принимать только закрытые свечи.
- [ ] Подключить `MarketDataPipeline` с единой границей `as_of`.
- [ ] Гарантировать graceful shutdown и durable checkpoint.
- [ ] Безопасно отклонять live mode.

**Выход:** 24-часовой soak без дублей, пропусков закрытых свечей и расхождения позиции.

## Milestone M2 — restart/idempotency (P0)

- [ ] E2E restart до/после signal, order и fill.
- [ ] E2E restart до/после PnL snapshot и checkpoint.
- [ ] Стабильные `run_id`, `signal_id`, `client_order_id`.
- [ ] Deterministic replay с одинаковыми state и PnL.

**Выход:** повторная обработка события не создаёт ордер/fill и не меняет подтверждённый факт.

## Milestone M3 — observability и fail-closed operation (P1)

- [ ] Heartbeat/health endpoint.
- [ ] Метрики candle lag, pipeline latency, checkpoint age, exposure, PnL/drawdown.
- [ ] Alert routing для stale data, DB outage, risk breach и state mismatch.
- [ ] Автоматический emergency stop и контролируемая процедура снятия.
- [ ] Runbook запуска, остановки, recovery и incident response.

**Выход:** fault-injection подтверждает блокировку новых входов и полный audit trail.

## Milestone M4 — reconciliation и отчётность (P1)

- [ ] Сверять orders, fills, positions, balance/equity и last market event.
- [ ] Разделить recoverable и fatal mismatches; неоднозначные случаи закрывать fail-closed.
- [ ] Запускать готовый DDS → MART ETL по расписанию.
- [ ] Создавать immutable daily report с costs, slippage, drawdown и rejects.

**Выход:** внесённое расхождение обнаруживается до нового входа; replay даёт тот же report.

## Milestone M5 — paper pilot (P1, минимум 90 дней)

До старта зафиксировать strategy/version, BTCUSDT/ETHUSDT Spot universe, initial
capital, risk limits, SLO, инфраструктуру и ответственных.

- [ ] 7-дневный наблюдаемый burn-in без изменения стратегии.
- [ ] Не менее 90 календарных дней и 100 закрытых сделок.
- [ ] Ноль необъяснённых reconciliation/determinism failures.
- [ ] Ноль duplicate orders после restart.
- [ ] Все критические incidents имеют alert и audit trail.
- [ ] Net PnL положителен после fees/slippage; drawdown в утверждённом limit.
- [ ] Результат не объясняется одним символом или коротким периодом.

**Выход:** только пакет данных для отдельного live design review, не автоматическое разрешение live.

## Постоянный поток — sealed holdout до 06.02.2027

- [x] Frozen v2 specification и unlock timestamp.
- [x] Инкрементальный RAW → DDS → derived → health pipeline.
- [ ] Продолжать загрузку только закрытых BTCUSDT/ETHUSDT 1h candles.
- [ ] Контролировать gaps, duplicates, provenance, checksums и determinism.
- [ ] После unlock и проверки sample requirements выполнить ровно один frozen run.

До unlock запрещены backtest, PnL, trade attribution и сравнение версий на holdout.

## Явно вне текущего scope

- Grid и новые стратегии до завершения оценки pilot candidate.
- ML/нейросети, futures, margin, leverage, short, HFT и auto-optimization.
- Live order manager до выполнения M1–M5 и отдельного go/no-go.
