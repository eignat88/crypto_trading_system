-- Add structured event correlation columns (run_id, signal_id) to paper
-- trading tables.  Every order, fill and position now carries a run_id that
-- links it to a single paper/live session, plus a signal_id that traces back
-- to the originating strategy signal.

ALTER TABLE paper_orders
ADD COLUMN IF NOT EXISTS run_id VARCHAR(64),
ADD COLUMN IF NOT EXISTS signal_id VARCHAR(64);

ALTER TABLE paper_fills
ADD COLUMN IF NOT EXISTS run_id VARCHAR(64),
ADD COLUMN IF NOT EXISTS signal_id VARCHAR(64);

-- Partial indexes for fast correlation lookups (only when values are present)
CREATE INDEX IF NOT EXISTS ix_paper_orders_run_id
ON paper_orders(run_id)
WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_paper_orders_signal_id
ON paper_orders(signal_id)
WHERE signal_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_paper_fills_run_id
ON paper_fills(run_id)
WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_paper_fills_signal_id
ON paper_fills(signal_id)
WHERE signal_id IS NOT NULL;
