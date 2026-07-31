CREATE TABLE IF NOT EXISTS risk_events (
    risk_event_id BIGSERIAL PRIMARY KEY,
    event_type TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity NUMERIC NOT NULL,
    price NUMERIC NOT NULL,
    reasons JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_risk_events_occurred_at ON risk_events (occurred_at DESC);

CREATE TABLE IF NOT EXISTS risk_engine_state (
    singleton_id SMALLINT PRIMARY KEY CHECK (singleton_id = 1),
    state JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
