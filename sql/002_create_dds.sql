-- DDS layer: normalized data for strategies

CREATE SCHEMA IF NOT EXISTS dds;

-- Instruments
CREATE TABLE IF NOT EXISTS dds.instrument (
    instrument_id       bigserial   PRIMARY KEY,
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    base_currency       text        NOT NULL,
    quote_currency      text        NOT NULL,
    is_active           boolean     NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dds_instrument
        UNIQUE (exchange_name, symbol)
);

-- Normalized candles
CREATE TABLE IF NOT EXISTS dds.candle (
    candle_id           bigserial   PRIMARY KEY,
    instrument_id       bigint      NOT NULL REFERENCES dds.instrument(instrument_id),
    interval_code       text        NOT NULL,
    open_time           timestamptz NOT NULL,
    close_time          timestamptz,
    open_price          numeric(28, 12) NOT NULL,
    high_price          numeric(28, 12) NOT NULL,
    low_price           numeric(28, 12) NOT NULL,
    close_price         numeric(28, 12) NOT NULL,
    volume              numeric(38, 12) NOT NULL DEFAULT 0,
    quote_volume        numeric(38, 12),
    trade_count         bigint,
    is_valid            boolean     NOT NULL DEFAULT true,
    validation_errors   jsonb,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dds_candle
        UNIQUE (instrument_id, interval_code, open_time),
    CONSTRAINT chk_dds_candle_ohlcv
        CHECK (
            high_price >= open_price
            AND high_price >= close_price
            AND low_price <= open_price
            AND low_price <= close_price
            AND high_price >= low_price
            AND volume >= 0
            AND close_price > 0
        ),
    -- Invalid RAW rows are rejected by RAW -> DDS ETL and recorded in
    -- data_quality_event. These two columns remain for backwards compatibility.
    CONSTRAINT chk_dds_candle_valid_only
        CHECK (is_valid = true AND validation_errors IS NULL)
);

-- Rejected source rows. DDS candles themselves contain valid, closed candles only.
CREATE TABLE IF NOT EXISTS dds.data_quality_event (
    event_id            bigserial   PRIMARY KEY,
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    interval_code       text        NOT NULL,
    open_time           timestamptz NOT NULL,
    check_name          text        NOT NULL,
    error_details       jsonb       NOT NULL,
    source_payload      jsonb,
    first_seen_at       timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz NOT NULL DEFAULT now(),
    occurrence_count    bigint      NOT NULL DEFAULT 1,
    CONSTRAINT uq_dds_data_quality_event
        UNIQUE (exchange_name, symbol, interval_code, open_time, check_name)
);

-- Incremental ETL watermark and execution journal.
CREATE TABLE IF NOT EXISTS dds.etl_checkpoint (
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    interval_code       text        NOT NULL,
    last_loaded_at      timestamptz NOT NULL DEFAULT '-infinity',
    last_run_at         timestamptz NOT NULL DEFAULT '-infinity',
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_dds_etl_checkpoint
        PRIMARY KEY (exchange_name, symbol, interval_code)
);

CREATE TABLE IF NOT EXISTS dds.etl_run (
    run_id              bigserial   PRIMARY KEY,
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    interval_code       text        NOT NULL,
    as_of               timestamptz NOT NULL,
    source_count        integer     NOT NULL DEFAULT 0,
    inserted_count      integer     NOT NULL DEFAULT 0,
    rejected_count      integer     NOT NULL DEFAULT 0,
    deferred_count      integer     NOT NULL DEFAULT 0,
    status              text        NOT NULL,
    error_message       text,
    started_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at        timestamptz,
    CONSTRAINT chk_dds_etl_run_status
        CHECK (status IN ('running', 'success', 'failed'))
);

-- Indicators
CREATE TABLE IF NOT EXISTS dds.indicator (
    indicator_id        bigserial   PRIMARY KEY,
    candle_id           bigint      NOT NULL REFERENCES dds.candle(candle_id),
    indicator_name      text        NOT NULL,
    indicator_value     numeric(28, 12),
    indicator_params    jsonb,
    calculated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dds_indicator
        UNIQUE (candle_id, indicator_name, indicator_params)
);

-- Market regime
CREATE TABLE IF NOT EXISTS dds.market_regime (
    regime_id           bigserial   PRIMARY KEY,
    candle_id           bigint      NOT NULL REFERENCES dds.candle(candle_id),
    regime              text        NOT NULL,
    confidence          numeric(5, 4) NOT NULL,
    reasons             jsonb,
    ema_20              numeric(28, 12),
    ema_50              numeric(28, 12),
    ema_200             numeric(28, 12),
    atr_percentage      numeric(10, 6),
    volatility          numeric(10, 6),
    calculated_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dds_market_regime
        UNIQUE (candle_id)
);

-- Strategy signals
CREATE TABLE IF NOT EXISTS dds.strategy_signal (
    signal_id           bigserial   PRIMARY KEY,
    strategy_name       text        NOT NULL,
    instrument_id       bigint      NOT NULL REFERENCES dds.instrument(instrument_id),
    signal_time         timestamptz NOT NULL,
    signal_type         text        NOT NULL,
    side                text        NOT NULL,
    quantity            numeric(38, 12),
    price               numeric(28, 12),
    stop_loss           numeric(28, 12),
    take_profit         numeric(28, 12),
    reason              text,
    regime_id           bigint      REFERENCES dds.market_regime(regime_id),
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_dds_candle_instrument_time
    ON dds.candle (instrument_id, interval_code, open_time DESC);

CREATE INDEX IF NOT EXISTS idx_dds_candle_valid
    ON dds.candle (is_valid) WHERE is_valid = true;

CREATE INDEX IF NOT EXISTS idx_dds_data_quality_event_source
    ON dds.data_quality_event (exchange_name, symbol, interval_code, open_time DESC);

CREATE INDEX IF NOT EXISTS idx_dds_etl_run_source
    ON dds.etl_run (exchange_name, symbol, interval_code, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_dds_indicator_candle
    ON dds.indicator (candle_id, indicator_name);

CREATE INDEX IF NOT EXISTS idx_dds_indicator_name
    ON dds.indicator (indicator_name, calculated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dds_market_regime_candle
    ON dds.market_regime (candle_id);

CREATE INDEX IF NOT EXISTS idx_dds_market_regime_time
    ON dds.market_regime (calculated_at DESC);

CREATE INDEX IF NOT EXISTS idx_dds_strategy_signal_time
    ON dds.strategy_signal (strategy_name, signal_time DESC);

CREATE INDEX IF NOT EXISTS idx_dds_strategy_signal_instrument
    ON dds.strategy_signal (instrument_id, signal_time DESC);
