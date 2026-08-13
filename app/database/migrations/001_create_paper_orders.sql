CREATE SCHEMA IF NOT EXISTS dds;

CREATE TABLE IF NOT EXISTS dds.paper_orders
(
    id BIGSERIAL PRIMARY KEY,

    order_id VARCHAR(64) NOT NULL,
    client_order_id VARCHAR(128),

    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(10) NOT NULL,
    order_type VARCHAR(20) NOT NULL,

    quantity NUMERIC(20,8) NOT NULL,
    price NUMERIC(20,8),

    status VARCHAR(20) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT uq_paper_orders_order_id
        UNIQUE(order_id)
);

CREATE INDEX IF NOT EXISTS ix_paper_orders_symbol_created
ON dds.paper_orders(symbol, created_at);
