CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.runtime_health (
    id BIGSERIAL PRIMARY KEY,
    runtime_id VARCHAR(100) NOT NULL,
    status VARCHAR(32) NOT NULL,
    sequence BIGINT NOT NULL DEFAULT 0 CHECK (sequence >= 0),
    last_cycle_time TIMESTAMPTZ,
    last_market_event_time TIMESTAMPTZ,
    uptime_seconds BIGINT NOT NULL DEFAULT 0 CHECK (uptime_seconds >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_runtime_health_runtime_time
    ON monitoring.runtime_health (runtime_id, created_at DESC);
