-- RAW Bybit schema for NautilusTrader integration

CREATE SCHEMA IF NOT EXISTS raw_bybit;

-- Bars (1-minute candles from Bybit)
CREATE TABLE IF NOT EXISTS raw_bybit.bars (
    id                  bigserial   PRIMARY KEY,
    instrument_id       text        NOT NULL,
    bar_type            text        NOT NULL,
    ts_event            timestamptz NOT NULL,
    ts_init             timestamptz NOT NULL,
    open_price          numeric(28, 12) NOT NULL,
    high_price          numeric(28, 12) NOT NULL,
    low_price           numeric(28, 12) NOT NULL,
    close_price         numeric(28, 12) NOT NULL,
    volume              numeric(38, 12) NOT NULL,
    quote_volume        numeric(38, 12),
    raw_payload         jsonb,
    request_id          text,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_bybit_bars
        UNIQUE (instrument_id, bar_type, ts_event)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_raw_bybit_bars_instrument
    ON raw_bybit.bars (instrument_id, ts_event DESC);

CREATE INDEX IF NOT EXISTS idx_raw_bybit_bars_type
    ON raw_bybit.bars (bar_type, ts_event DESC);

-- Trades (optional, for future use)
CREATE TABLE IF NOT EXISTS raw_bybit.trades (
    id                  bigserial   PRIMARY KEY,
    instrument_id       text        NOT NULL,
    trade_id            text        NOT NULL,
    ts_event            timestamptz NOT NULL,
    ts_init             timestamptz NOT NULL,
    price               numeric(28, 12) NOT NULL,
    quantity            numeric(38, 12) NOT NULL,
    side                text        NOT NULL,
    raw_payload         jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_bybit_trades
        UNIQUE (instrument_id, trade_id)
);

-- Quotes (optional, for future use)
CREATE TABLE IF NOT EXISTS raw_bybit.quotes (
    id                  bigserial   PRIMARY KEY,
    instrument_id       text        NOT NULL,
    ts_event            timestamptz NOT NULL,
    ts_init             timestamptz NOT NULL,
    bid_price           numeric(28, 12) NOT NULL,
    bid_size            numeric(38, 12) NOT NULL,
    ask_price           numeric(28, 12) NOT NULL,
    ask_size            numeric(38, 12) NOT NULL,
    raw_payload         jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_raw_bybit_quotes
        UNIQUE (instrument_id, ts_event)
);

-- ETL checkpoint
CREATE TABLE IF NOT EXISTS raw_bybit.etl_checkpoint (
    instrument_id       text        NOT NULL,
    bar_type            text        NOT NULL,
    last_loaded_at      timestamptz NOT NULL DEFAULT '-infinity',
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, bar_type)
);
