-- DDS to MART ETL: Aggregate daily performance from DDS candles
-- This script creates functions for idempotent MART layer population

CREATE SCHEMA IF NOT EXISTS mart;

-- ETL run log for MART layer
CREATE TABLE IF NOT EXISTS mart.etl_run (
    run_id              bigserial   PRIMARY KEY,
    run_date            date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    rows_processed      integer     NOT NULL DEFAULT 0,
    status              text        NOT NULL,
    error_message       text,
    started_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at        timestamptz,
    CONSTRAINT chk_mart_etl_run_status
        CHECK (status IN ('running', 'success', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_mart_etl_run_date
    ON mart.etl_run (run_date DESC);

-- Daily OHLCV aggregation function
-- Aggregates hourly candles into daily bars
CREATE OR REPLACE FUNCTION mart.refresh_daily_ohlcv(
    p_exchange_name text DEFAULT 'bybit',
    p_target_date date DEFAULT NULL
)
RETURNS TABLE (
    rows_processed integer
) AS $$
DECLARE
    v_rows_processed integer := 0;
    v_start_date date;
    v_end_date date;
BEGIN
    -- If no specific date provided, process yesterday's data (to ensure all candles are closed)
    IF p_target_date IS NULL THEN
        v_start_date := CURRENT_DATE - INTERVAL '1 day';
        v_end_date := CURRENT_DATE;
    ELSE
        v_start_date := p_target_date;
        v_end_date := p_target_date + INTERVAL '1 day';
    END IF;

    -- Insert or update daily aggregations
    -- Uses first candle open, last candle close, max high, min low, sum volume
    WITH daily_agg AS (
        SELECT
            DATE_TRUNC('day', c.open_time)::date as report_date,
            i.exchange_name,
            i.symbol,
            FIRST(c.open_price ORDER BY c.open_time) as open_price,
            LAST(c.close_price ORDER BY c.open_time) as close_price,
            MAX(c.high_price) as high_price,
            MIN(c.low_price) as low_price,
            SUM(c.volume) as total_volume,
            COUNT(*) as candle_count
        FROM dds.candle c
        JOIN dds.instrument i ON c.instrument_id = i.instrument_id
        WHERE i.exchange_name = p_exchange_name
          AND c.is_valid = true
          AND c.open_time >= v_start_date
          AND c.open_time < v_end_date
        GROUP BY DATE_TRUNC('day', c.open_time)::date, i.exchange_name, i.symbol
    )
    INSERT INTO mart.daily_ohlcv (
        report_date, exchange_name, symbol,
        open_price, high_price, low_price, close_price,
        total_volume, candle_count
    )
    SELECT
        report_date, exchange_name, symbol,
        open_price, high_price, low_price, close_price,
        total_volume, candle_count
    FROM daily_agg
    ON CONFLICT (report_date, exchange_name, symbol)
    DO UPDATE SET
        open_price = EXCLUDED.open_price,
        high_price = EXCLUDED.high_price,
        low_price = EXCLUDED.low_price,
        close_price = EXCLUDED.close_price,
        total_volume = EXCLUDED.total_volume,
        candle_count = EXCLUDED.candle_count,
        updated_at = now()
    RETURNING 1
    INTO v_rows_processed;

    -- Get actual count
    GET DIAGNOSTICS v_rows_processed = ROW_COUNT;

    RETURN QUERY SELECT v_rows_processed;
END;
$$ LANGUAGE plpgsql;

-- Create daily OHLCV table if not exists
CREATE TABLE IF NOT EXISTS mart.daily_ohlcv (
    id                  bigserial   PRIMARY KEY,
    report_date         date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    symbol              text        NOT NULL,
    open_price          numeric(28, 12) NOT NULL,
    high_price          numeric(28, 12) NOT NULL,
    low_price           numeric(28, 12) NOT NULL,
    close_price         numeric(28, 12) NOT NULL,
    total_volume        numeric(38, 12) NOT NULL DEFAULT 0,
    candle_count        integer     NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_daily_ohlcv
        UNIQUE (report_date, exchange_name, symbol)
);

CREATE INDEX IF NOT EXISTS idx_mart_daily_ohlcv_date
    ON mart.daily_ohlcv (report_date DESC);

CREATE INDEX IF NOT EXISTS idx_mart_daily_ohlcv_symbol
    ON mart.daily_ohlcv (symbol, report_date DESC);

-- Strategy performance placeholder (to be filled after backtests)
-- Structure is already defined in 003_create_mart.sql, this just ensures it exists
CREATE TABLE IF NOT EXISTS mart.strategy_performance (
    id                  bigserial   PRIMARY KEY,
    strategy_name       text        NOT NULL,
    report_date         date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    total_pnl           numeric(38, 12) NOT NULL DEFAULT 0,
    total_pnl_pct       numeric(10, 6) NOT NULL DEFAULT 0,
    trades_count        integer     NOT NULL DEFAULT 0,
    winning_trades      integer     NOT NULL DEFAULT 0,
    losing_trades       integer     NOT NULL DEFAULT 0,
    win_rate            numeric(5, 4) NOT NULL DEFAULT 0,
    profit_factor       numeric(10, 4) NOT NULL DEFAULT 0,
    max_drawdown        numeric(10, 6) NOT NULL DEFAULT 0,
    sharpe_ratio        numeric(10, 4),
    avg_trade_pnl       numeric(38, 12) NOT NULL DEFAULT 0,
    avg_win             numeric(38, 12) NOT NULL DEFAULT 0,
    avg_loss            numeric(38, 12) NOT NULL DEFAULT 0,
    max_consecutive_losses integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_strategy_performance
        UNIQUE (strategy_name, report_date, exchange_name)
);

-- Function to refresh strategy performance (placeholder - returns 0 rows)
CREATE OR REPLACE FUNCTION mart.refresh_strategy_performance(
    p_strategy_name text DEFAULT NULL,
    p_exchange_name text DEFAULT 'bybit',
    p_target_date date DEFAULT NULL
)
RETURNS TABLE (
    rows_processed integer
) AS $$
DECLARE
    v_rows_processed integer := 0;
BEGIN
    -- Placeholder: strategy performance will be populated after backtest execution
    -- For now, return 0 to indicate no processing was done
    RETURN QUERY SELECT 0;
END;
$$ LANGUAGE plpgsql;

-- Main ETL orchestration function
CREATE OR REPLACE FUNCTION mart.run_etl(
    p_exchange_name text DEFAULT 'bybit',
    p_target_date date DEFAULT NULL,
    p_log_run boolean DEFAULT true
)
RETURNS TABLE (
    daily_ohlcv_rows integer,
    strategy_perf_rows integer
) AS $$
DECLARE
    v_run_id bigint;
    v_daily_rows integer := 0;
    v_strategy_rows integer := 0;
    v_total_rows integer := 0;
    v_status text := 'running';
    v_error_message text;
BEGIN
    -- Log run start if requested
    IF p_log_run THEN
        INSERT INTO mart.etl_run (run_date, exchange_name, status)
        VALUES (COALESCE(p_target_date, CURRENT_DATE - 1), p_exchange_name, 'running')
        RETURNING run_id INTO v_run_id;
    END IF;

    BEGIN
        -- Refresh daily OHLCV
        SELECT COALESCE(SUM(rows_processed), 0) INTO v_daily_rows
        FROM mart.refresh_daily_ohlcv(p_exchange_name, p_target_date);

        -- Refresh strategy performance (placeholder)
        SELECT COALESCE(SUM(rows_processed), 0) INTO v_strategy_rows
        FROM mart.refresh_strategy_performance(NULL, p_exchange_name, p_target_date);

        v_total_rows := v_daily_rows + v_strategy_rows;
        v_status := 'success';

    EXCEPTION WHEN OTHERS THEN
        v_status := 'failed';
        v_error_message := SQLERRM;
        RAISE;
    FINALLY
        -- Update run log
        IF p_log_run AND v_run_id IS NOT NULL THEN
            UPDATE mart.etl_run
            SET rows_processed = v_total_rows,
                status = v_status,
                error_message = v_error_message,
                completed_at = now()
            WHERE run_id = v_run_id;
        END IF;
    END;

    RETURN QUERY SELECT v_daily_rows, v_strategy_rows;
END;
$$ LANGUAGE plpgsql;
