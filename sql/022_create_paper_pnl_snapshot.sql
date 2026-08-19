-- Durable reporting state used to rebuild paper-trading PnL and equity curves.

CREATE SCHEMA IF NOT EXISTS dds;

CREATE TABLE IF NOT EXISTS dds.paper_pnl_snapshots
(
    snapshot_time   TIMESTAMPTZ     NOT NULL,
    sequence_no     BIGINT          NOT NULL CHECK (sequence_no >= 0),
    equity          NUMERIC(38, 12) NOT NULL,
    realized_pnl    NUMERIC(38, 12) NOT NULL,
    unrealized_pnl  NUMERIC(38, 12) NOT NULL,
    total_pnl       NUMERIC(38, 12) NOT NULL,
    fees_paid       NUMERIC(38, 12) NOT NULL,
    slippage        NUMERIC(38, 12) NOT NULL,
    cash_balance    NUMERIC(38, 12) NOT NULL,
    position_value  NUMERIC(38, 12) NOT NULL,
    drawdown        NUMERIC(38, 12) NOT NULL,
    drawdown_pct    NUMERIC(38, 12) NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (snapshot_time, sequence_no)
);

CREATE INDEX IF NOT EXISTS ix_paper_pnl_snapshots_sequence
ON dds.paper_pnl_snapshots(sequence_no);
