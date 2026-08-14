CREATE TABLE IF NOT EXISTS paper_runtime_state
(
    id INTEGER PRIMARY KEY,
    last_processed_timestamp TIMESTAMPTZ,
    last_market_sequence BIGINT NOT NULL DEFAULT 0,
    cash_balance NUMERIC(20,8) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_balances
(
    id BIGSERIAL PRIMARY KEY,
    asset VARCHAR(20) NOT NULL,
    balance NUMERIC(20,8) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(asset)
);

CREATE TABLE IF NOT EXISTS paper_positions
(
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(20,8) NOT NULL,
    average_price NUMERIC(20,8) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(symbol)
);

CREATE TABLE IF NOT EXISTS paper_orders
(
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(order_id)
);

CREATE TABLE IF NOT EXISTS paper_fills
(
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    quantity NUMERIC(20,8) NOT NULL,
    price NUMERIC(20,8) NOT NULL,
    commission NUMERIC(20,8) NOT NULL DEFAULT 0,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_paper_fills_order_id
ON paper_fills(order_id);
