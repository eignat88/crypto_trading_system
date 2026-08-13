CREATE TABLE IF NOT EXISTS dds.paper_fills
(
    id BIGSERIAL PRIMARY KEY,
    fill_id VARCHAR(64) UNIQUE NOT NULL,
    order_id VARCHAR(64) NOT NULL,
    symbol VARCHAR(32) NOT NULL,
    quantity NUMERIC(38,18) NOT NULL,
    price NUMERIC(38,18) NOT NULL,
    commission NUMERIC(38,18) NOT NULL DEFAULT 0,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dds.paper_positions
(
    symbol VARCHAR(32) PRIMARY KEY,
    quantity NUMERIC(38,18) NOT NULL DEFAULT 0,
    average_price NUMERIC(38,18) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dds.paper_balance
(
    asset VARCHAR(16) PRIMARY KEY,
    free NUMERIC(38,18) NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dds.paper_checkpoint
(
    checkpoint_id UUID PRIMARY KEY,
    state JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
