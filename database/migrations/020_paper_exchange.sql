CREATE TABLE IF NOT EXISTS dds.paper_orders (
    id BIGSERIAL PRIMARY KEY,
    order_id VARCHAR(64) NOT NULL UNIQUE,
    client_order_id VARCHAR(128) NOT NULL UNIQUE,
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(16) NOT NULL,
    quantity NUMERIC(38,18) NOT NULL,
    price NUMERIC(38,18),
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_paper_orders_symbol
ON dds.paper_orders(symbol, created_at);
