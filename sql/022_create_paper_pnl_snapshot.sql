CREATE SCHEMA IF NOT EXISTS dds;

CREATE TABLE IF NOT EXISTS dds.paper_pnl_snapshot (
    snapshot_id       bigserial PRIMARY KEY,
    snapshot_time     timestamptz NOT NULL,
    sequence          bigint NOT NULL,
    equity            numeric(38, 12) NOT NULL,
    realized_pnl      numeric(38, 12) NOT NULL DEFAULT 0,
    unrealized_pnl    numeric(38, 12) NOT NULL DEFAULT 0,
    total_pnl         numeric(38, 12) NOT NULL DEFAULT 0,
    fees_paid         numeric(38, 12) NOT NULL DEFAULT 0,
    slippage          numeric(38, 12) NOT NULL DEFAULT 0,
    cash_balance      numeric(38, 12) NOT NULL DEFAULT 0,
    position_value    numeric(38, 12) NOT NULL DEFAULT 0,
    drawdown          numeric(38, 12) NOT NULL DEFAULT 0,
    drawdown_pct      numeric(10, 6) NOT NULL DEFAULT 0,
    created_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dds_paper_pnl_snapshot UNIQUE (snapshot_time, sequence)
);

CREATE INDEX IF NOT EXISTS idx_dds_paper_pnl_snapshot_time
    ON dds.paper_pnl_snapshot (snapshot_time DESC);
CREATE INDEX IF NOT EXISTS idx_dds_paper_pnl_snapshot_sequence
    ON dds.paper_pnl_snapshot (sequence);
