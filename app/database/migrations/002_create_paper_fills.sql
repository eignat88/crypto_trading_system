CREATE TABLE IF NOT EXISTS dds.paper_fills
(
    id BIGSERIAL PRIMARY KEY,

    fill_id VARCHAR(64) NOT NULL,
    order_id VARCHAR(64) NOT NULL,

    symbol VARCHAR(32) NOT NULL,

    quantity NUMERIC(20,8) NOT NULL,
    price NUMERIC(20,8) NOT NULL,

    commission NUMERIC(20,8) DEFAULT 0,

    executed_at TIMESTAMPTZ NOT NULL,

    CONSTRAINT uq_paper_fills_fill_id
        UNIQUE(fill_id)
);

CREATE INDEX IF NOT EXISTS ix_paper_fills_order_id
ON dds.paper_fills(order_id);
