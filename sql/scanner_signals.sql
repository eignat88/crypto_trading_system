-- Scanner signals table for persisting detected setups

CREATE TABLE IF NOT EXISTS scanner_signals (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    setup_type VARCHAR(30) NOT NULL,
    direction VARCHAR(20) NOT NULL,
    score DECIMAL(10, 2) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    candle_time TIMESTAMPTZ,
    price DECIMAL(30, 10) NOT NULL,
    breakout_level DECIMAL(30, 10),
    atr DECIMAL(30, 10),
    ema20 DECIMAL(30, 10),
    ema50 DECIMAL(30, 10),
    ema200 DECIMAL(30, 10),
    volume DECIMAL(30, 10),
    volume_ma20 DECIMAL(30, 10),
    scanner_version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    parameters_version VARCHAR(20) NOT NULL DEFAULT 'v1',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (symbol, setup_type, candle_time, breakout_level)
);

CREATE INDEX IF NOT EXISTS idx_scanner_signals_symbol ON scanner_signals (symbol);
CREATE INDEX IF NOT EXISTS idx_scanner_signals_setup_type ON scanner_signals (setup_type);
CREATE INDEX IF NOT EXISTS idx_scanner_signals_detected_at ON scanner_signals (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_scanner_signals_score ON scanner_signals (score DESC);
