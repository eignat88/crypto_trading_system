CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.runtime_health (
    runtime_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    heartbeat_time TIMESTAMPTZ NOT NULL,
    last_market_event_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runtime_health_heartbeat_time
    ON monitoring.runtime_health (heartbeat_time DESC);
