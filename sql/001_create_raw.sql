-- RAW layer: stores data as close to exchange response as possible

CREATE SCHEMA IF NOT EXISTS raw_market;
CREATE SCHEMA IF NOT EXISTS raw_account;
CREATE SCHEMA IF NOT EXISTS raw_system;

-- Market data: candles
CREATE TABLE IF NOT EXISTS raw_market.candles
(
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    interval_code       text        NOT NULL,
    open_time           timestamptz NOT NULL,
    close_time          timestamptz,
    open_price          numeric(28, 12) NOT NULL,
    high_price          numeric(28, 12) NOT NULL,
    low_price           numeric(28, 12) NOT NULL,
    close_price         numeric(28, 12) NOT NULL,
    volume              numeric(38, 12),
    quote_volume        numeric(38, 12),
    trade_count         bigint,
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_market_candles
        PRIMARY KEY
        (
            exchange_name,
            symbol,
            interval_code,
            open_time
        )
);

-- Market data: trades
CREATE TABLE IF NOT EXISTS raw_market.trades
(
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    trade_id            text        NOT NULL,
    price               numeric(28, 12) NOT NULL,
    quantity            numeric(38, 12) NOT NULL,
    trade_time          timestamptz NOT NULL,
    is_buyer_maker      boolean,
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_market_trades
        PRIMARY KEY (exchange_name, symbol, trade_id)
);

-- Market data: order book
CREATE TABLE IF NOT EXISTS raw_market.order_book
(
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    snapshot_time       timestamptz NOT NULL,
    bids                jsonb       NOT NULL,
    asks                jsonb       NOT NULL,
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_market_order_book
        PRIMARY KEY (exchange_name, symbol, snapshot_time)
);

-- Market data: tickers
CREATE TABLE IF NOT EXISTS raw_market.tickers
(
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    ticker_time         timestamptz NOT NULL,
    last_price          numeric(28, 12),
    bid_price           numeric(28, 12),
    ask_price           numeric(28, 12),
    volume_24h          numeric(38, 12),
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_market_tickers
        PRIMARY KEY (exchange_name, symbol, ticker_time)
);

-- Account data: balances
CREATE TABLE IF NOT EXISTS raw_account.balances
(
    exchange_name       text        NOT NULL,
    currency            text        NOT NULL,
    balance_time        timestamptz NOT NULL,
    available           numeric(38, 12),
    locked              numeric(38, 12),
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_account_balances
        PRIMARY KEY (exchange_name, currency, balance_time)
);

-- Account data: orders
CREATE TABLE IF NOT EXISTS raw_account.orders
(
    exchange_name       text        NOT NULL,
    order_id            text        NOT NULL,
    client_order_id     text,
    symbol              text        NOT NULL,
    side                text        NOT NULL,
    order_type          text        NOT NULL,
    quantity            numeric(38, 12) NOT NULL,
    price               numeric(28, 12),
    status              text        NOT NULL,
    created_at          timestamptz NOT NULL,
    updated_at          timestamptz,
    filled_quantity     numeric(38, 12),
    average_price       numeric(28, 12),
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_account_orders
        PRIMARY KEY (exchange_name, order_id)
);

-- Account data: executions
CREATE TABLE IF NOT EXISTS raw_account.executions
(
    exchange_name       text        NOT NULL,
    execution_id        text        NOT NULL,
    order_id            text        NOT NULL,
    symbol              text        NOT NULL,
    side                text        NOT NULL,
    price               numeric(28, 12) NOT NULL,
    quantity            numeric(38, 12) NOT NULL,
    fee                 numeric(38, 12),
    fee_currency        text,
    execution_time      timestamptz NOT NULL,
    source_payload      jsonb,
    loaded_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_raw_account_executions
        PRIMARY KEY (exchange_name, execution_id)
);

-- System: API responses log
CREATE TABLE IF NOT EXISTS raw_system.api_responses
(
    id                  bigserial   PRIMARY KEY,
    exchange_name       text        NOT NULL,
    endpoint            text        NOT NULL,
    request_id          text,
    request_time        timestamptz NOT NULL,
    response_time       timestamptz,
    status_code         integer,
    request_payload     jsonb,
    response_payload    jsonb,
    error_message       text,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Loading journal for checkpoint tracking
CREATE TABLE IF NOT EXISTS raw_system.loading_journal
(
    id                  bigserial   PRIMARY KEY,
    exchange_name       text        NOT NULL,
    symbol              text        NOT NULL,
    interval_code       text        NOT NULL,
    start_time          timestamptz NOT NULL,
    end_time            timestamptz NOT NULL,
    rows_loaded         integer     NOT NULL DEFAULT 0,
    status              text        NOT NULL DEFAULT 'success',
    error_message       text,
    started_at          timestamptz NOT NULL DEFAULT now(),
    completed_at        timestamptz
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_candles_symbol_interval
    ON raw_market.candles (exchange_name, symbol, interval_code, open_time);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON raw_market.trades (exchange_name, symbol, trade_time);

CREATE INDEX IF NOT EXISTS idx_orders_symbol_status
    ON raw_account.orders (exchange_name, symbol, status);

CREATE INDEX IF NOT EXISTS idx_executions_order
    ON raw_account.executions (exchange_name, order_id);

CREATE INDEX IF NOT EXISTS idx_api_responses_endpoint_time
    ON raw_system.api_responses (exchange_name, endpoint, request_time);

CREATE INDEX IF NOT EXISTS idx_loading_journal_symbol
    ON raw_system.loading_journal (exchange_name, symbol, interval_code);
