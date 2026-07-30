-- Idempotent RAW -> DDS candle pipeline.
-- Apply after 001_create_raw.sql and 002_create_dds.sql.

-- Make this migration safe for databases created with an older 002 migration.
CREATE TABLE IF NOT EXISTS dds.data_quality_event (
    event_id bigserial PRIMARY KEY,
    exchange_name text NOT NULL,
    symbol text NOT NULL,
    interval_code text NOT NULL,
    open_time timestamptz NOT NULL,
    check_name text NOT NULL,
    error_details jsonb NOT NULL,
    source_payload jsonb,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    occurrence_count bigint NOT NULL DEFAULT 1,
    UNIQUE (exchange_name, symbol, interval_code, open_time, check_name)
);

CREATE TABLE IF NOT EXISTS dds.etl_checkpoint (
    exchange_name text NOT NULL,
    symbol text NOT NULL,
    interval_code text NOT NULL,
    last_loaded_at timestamptz NOT NULL DEFAULT '-infinity',
    last_run_at timestamptz NOT NULL DEFAULT '-infinity',
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange_name, symbol, interval_code)
);

CREATE TABLE IF NOT EXISTS dds.etl_run (
    run_id bigserial PRIMARY KEY,
    exchange_name text NOT NULL,
    symbol text NOT NULL,
    interval_code text NOT NULL,
    as_of timestamptz NOT NULL,
    source_count integer NOT NULL DEFAULT 0,
    inserted_count integer NOT NULL DEFAULT 0,
    rejected_count integer NOT NULL DEFAULT 0,
    deferred_count integer NOT NULL DEFAULT 0,
    status text NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    error_message text,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'dds.candle'::regclass
          AND conname = 'chk_dds_candle_valid_only'
    ) THEN
        ALTER TABLE dds.candle
            ADD CONSTRAINT chk_dds_candle_valid_only
            CHECK (is_valid = true AND validation_errors IS NULL) NOT VALID;
    END IF;
END;
$$;
ALTER TABLE dds.candle VALIDATE CONSTRAINT chk_dds_candle_valid_only;

CREATE INDEX IF NOT EXISTS idx_dds_data_quality_event_source
    ON dds.data_quality_event (exchange_name, symbol, interval_code, open_time DESC);
CREATE INDEX IF NOT EXISTS idx_dds_etl_run_source
    ON dds.etl_run (exchange_name, symbol, interval_code, started_at DESC);

-- Seed the explicitly supported instruments without changing existing metadata.
INSERT INTO dds.instrument (exchange_name, symbol, base_currency, quote_currency)
VALUES
    ('bybit', 'BTCUSDT', 'BTC', 'USDT'),
    ('bybit', 'ETHUSDT', 'ETH', 'USDT')
ON CONFLICT (exchange_name, symbol) DO NOTHING;

CREATE OR REPLACE FUNCTION dds.load_raw_candles(
    p_exchange_name text DEFAULT 'bybit',
    p_symbol text DEFAULT NULL,
    p_interval_code text DEFAULT NULL,
    p_as_of timestamptz DEFAULT clock_timestamp()
)
RETURNS TABLE (
    run_id bigint,
    exchange_name text,
    symbol text,
    interval_code text,
    source_count integer,
    inserted_count integer,
    rejected_count integer,
    deferred_count integer
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_stream record;
    v_run_id bigint;
    v_source integer;
    v_inserted integer;
    v_rejected integer;
    v_deferred integer;
    v_checkpoint timestamptz;
    v_last_run timestamptz;
    v_upper_loaded_at timestamptz;
BEGIN
    IF p_as_of IS NULL THEN
        RAISE EXCEPTION 'p_as_of must not be NULL';
    END IF;

    INSERT INTO dds.instrument (exchange_name, symbol, base_currency, quote_currency)
    VALUES ('bybit', 'BTCUSDT', 'BTC', 'USDT'), ('bybit', 'ETHUSDT', 'ETH', 'USDT')
    ON CONFLICT (exchange_name, symbol) DO NOTHING;

    FOR v_stream IN
        SELECT DISTINCT r.exchange_name, r.symbol, r.interval_code
        FROM raw_market.candles r
        JOIN dds.instrument i
          ON i.exchange_name = r.exchange_name AND i.symbol = r.symbol
        WHERE r.exchange_name = p_exchange_name
          AND (p_symbol IS NULL OR r.symbol = p_symbol)
          AND (p_interval_code IS NULL OR r.interval_code = p_interval_code)
        ORDER BY r.exchange_name, r.symbol, r.interval_code
    LOOP
        -- One writer per stream. The checkpoint row is also the concurrency lock.
        INSERT INTO dds.etl_checkpoint (exchange_name, symbol, interval_code)
        VALUES (v_stream.exchange_name, v_stream.symbol, v_stream.interval_code)
        ON CONFLICT DO NOTHING;

        SELECT c.last_loaded_at, c.last_run_at
          INTO v_checkpoint, v_last_run
        FROM dds.etl_checkpoint c
        WHERE c.exchange_name = v_stream.exchange_name
          AND c.symbol = v_stream.symbol
          AND c.interval_code = v_stream.interval_code
        FOR UPDATE;

        SELECT COALESCE(max(r.loaded_at), v_checkpoint)
          INTO v_upper_loaded_at
        FROM raw_market.candles r
        WHERE r.exchange_name = v_stream.exchange_name
          AND r.symbol = v_stream.symbol
          AND r.interval_code = v_stream.interval_code
          AND r.loaded_at <= p_as_of;

        INSERT INTO dds.etl_run (
            exchange_name, symbol, interval_code, as_of, status
        ) VALUES (
            v_stream.exchange_name, v_stream.symbol, v_stream.interval_code, p_as_of, 'running'
        ) RETURNING dds.etl_run.run_id INTO v_run_id;

        DROP TABLE IF EXISTS pg_temp.raw_to_dds_candidates;
        CREATE TEMP TABLE raw_to_dds_candidates ON COMMIT DROP AS
        SELECT r.*,
               ARRAY_REMOVE(ARRAY[
                   CASE WHEN r.close_time IS NULL OR r.close_time <= r.open_time
                        THEN 'invalid_close_time' END,
                   CASE WHEN r.open_price <= 0 OR r.high_price <= 0
                                  OR r.low_price <= 0 OR r.close_price <= 0
                        THEN 'non_positive_price' END,
                   CASE WHEN r.high_price < r.open_price OR r.high_price < r.close_price
                                  OR r.low_price > r.open_price OR r.low_price > r.close_price
                                  OR r.high_price < r.low_price
                        THEN 'invalid_ohlc' END,
                   CASE WHEN COALESCE(r.volume, 0) < 0
                                  OR r.quote_volume < 0 OR r.trade_count < 0
                        THEN 'negative_activity' END
               ], NULL) AS errors
        FROM raw_market.candles r
        WHERE r.exchange_name = v_stream.exchange_name
          AND r.symbol = v_stream.symbol
          AND r.interval_code = v_stream.interval_code
          AND r.loaded_at <= v_upper_loaded_at
          AND (
              r.loaded_at > v_checkpoint
              OR (r.close_time > v_last_run AND r.close_time <= p_as_of)
          );

        SELECT count(*) FILTER (WHERE close_time IS NOT NULL AND close_time <= p_as_of),
               count(*) FILTER (WHERE close_time IS NULL OR close_time > p_as_of)
          INTO v_source, v_deferred
        FROM raw_to_dds_candidates;

        INSERT INTO dds.data_quality_event (
            exchange_name, symbol, interval_code, open_time, check_name,
            error_details, source_payload
        )
        SELECT c.exchange_name, c.symbol, c.interval_code, c.open_time, e.check_name,
               jsonb_build_object('failed_checks', to_jsonb(c.errors)), c.source_payload
        FROM raw_to_dds_candidates c
        CROSS JOIN LATERAL unnest(c.errors) AS e(check_name)
        WHERE c.close_time IS NOT NULL AND c.close_time <= p_as_of
        ON CONFLICT (exchange_name, symbol, interval_code, open_time, check_name)
        DO UPDATE SET last_seen_at = now(),
                      occurrence_count = dds.data_quality_event.occurrence_count + 1,
                      error_details = EXCLUDED.error_details,
                      source_payload = EXCLUDED.source_payload;

        SELECT count(*) INTO v_rejected
        FROM raw_to_dds_candidates
        WHERE close_time IS NOT NULL AND close_time <= p_as_of
          AND cardinality(errors) > 0;

        INSERT INTO dds.candle (
            instrument_id, interval_code, open_time, close_time, open_price,
            high_price, low_price, close_price, volume, quote_volume, trade_count
        )
        SELECT i.instrument_id, c.interval_code, c.open_time, c.close_time,
               c.open_price, c.high_price, c.low_price, c.close_price,
               COALESCE(c.volume, 0), c.quote_volume, c.trade_count
        FROM raw_to_dds_candidates c
        JOIN dds.instrument i
          ON i.exchange_name = c.exchange_name AND i.symbol = c.symbol
        WHERE c.close_time IS NOT NULL AND c.close_time <= p_as_of
          AND cardinality(c.errors) = 0
        ON CONFLICT (instrument_id, interval_code, open_time) DO NOTHING;
        GET DIAGNOSTICS v_inserted = ROW_COUNT;

        UPDATE dds.etl_checkpoint c
        SET last_loaded_at = v_upper_loaded_at,
            last_run_at = p_as_of,
            updated_at = clock_timestamp()
        WHERE c.exchange_name = v_stream.exchange_name
          AND c.symbol = v_stream.symbol
          AND c.interval_code = v_stream.interval_code;

        UPDATE dds.etl_run r
        SET source_count = v_source,
            inserted_count = v_inserted,
            rejected_count = v_rejected,
            deferred_count = v_deferred,
            status = 'success',
            completed_at = clock_timestamp()
        WHERE r.run_id = v_run_id;

        run_id := v_run_id;
        exchange_name := v_stream.exchange_name;
        symbol := v_stream.symbol;
        interval_code := v_stream.interval_code;
        source_count := v_source;
        inserted_count := v_inserted;
        rejected_count := v_rejected;
        deferred_count := v_deferred;
        RETURN NEXT;
    END LOOP;
END;
$$;

COMMENT ON FUNCTION dds.load_raw_candles(text, text, text, timestamptz) IS
'Loads valid closed RAW candles idempotently; rejects invalid rows into data_quality_event and returns per-stream counts.';
