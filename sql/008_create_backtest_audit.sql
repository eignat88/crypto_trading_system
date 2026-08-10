-- Reproducible backtest audit persistence.
-- One backtest run owns its complete signal/risk/order/fill trail.

CREATE SCHEMA IF NOT EXISTS mart;

CREATE TABLE IF NOT EXISTS mart.backtest_run (
    run_id                  uuid            PRIMARY KEY,
    run_fingerprint         text            NOT NULL UNIQUE,
    created_at              timestamptz     NOT NULL,
    git_commit              text,
    exchange_name           text            NOT NULL,
    symbol                  text            NOT NULL,
    interval_code           text            NOT NULL,
    period_start            timestamptz     NOT NULL,
    period_end              timestamptz     NOT NULL,
    candle_count            integer         NOT NULL CHECK (candle_count > 0),
    random_seed             integer         NOT NULL,
    strategy_name           text            NOT NULL,
    parameters_version      text            NOT NULL,
    strategy_parameters     jsonb           NOT NULL,
    backtest_config         jsonb           NOT NULL,
    initial_balance         numeric(38, 12) NOT NULL CHECK (initial_balance > 0),
    final_equity            numeric(38, 12) NOT NULL,
    total_pnl               numeric(38, 12) NOT NULL,
    total_trades            integer         NOT NULL CHECK (total_trades >= 0),
    winning_trades          integer         NOT NULL CHECK (winning_trades >= 0),
    losing_trades           integer         NOT NULL CHECK (losing_trades >= 0),
    win_rate                numeric(18, 12) NOT NULL,
    profit_factor           numeric(38, 12) NOT NULL,
    average_trade           numeric(38, 12) NOT NULL,
    average_win             numeric(38, 12) NOT NULL,
    average_loss            numeric(38, 12) NOT NULL,
    max_drawdown            numeric(18, 12) NOT NULL,
    max_consecutive_losses  integer         NOT NULL CHECK (max_consecutive_losses >= 0),
    audit_file              text,
    persisted_at            timestamptz     NOT NULL DEFAULT now(),
    CONSTRAINT ck_backtest_period CHECK (period_end > period_start),
    CONSTRAINT ck_backtest_trade_counts
        CHECK (winning_trades + losing_trades = total_trades)
);

CREATE TABLE IF NOT EXISTS mart.backtest_signal (
    run_id              uuid        NOT NULL REFERENCES mart.backtest_run(run_id) ON DELETE CASCADE,
    sequence_no         integer     NOT NULL CHECK (sequence_no > 0),
    action              text        NOT NULL,
    symbol              text        NOT NULL,
    signal_time         timestamptz NOT NULL,
    strategy_name       text        NOT NULL,
    parameters_version  text        NOT NULL,
    regime              text,
    reason              text        NOT NULL DEFAULT '',
    payload             jsonb       NOT NULL,
    PRIMARY KEY (run_id, sequence_no)
);

CREATE TABLE IF NOT EXISTS mart.backtest_risk_decision (
    run_id              uuid        NOT NULL REFERENCES mart.backtest_run(run_id) ON DELETE CASCADE,
    sequence_no         integer     NOT NULL CHECK (sequence_no > 0),
    order_id            text        NOT NULL,
    approved            boolean     NOT NULL,
    risk_level          text        NOT NULL,
    payload             jsonb       NOT NULL,
    PRIMARY KEY (run_id, sequence_no),
    UNIQUE (run_id, order_id)
);

CREATE TABLE IF NOT EXISTS mart.backtest_order (
    run_id              uuid        NOT NULL REFERENCES mart.backtest_run(run_id) ON DELETE CASCADE,
    sequence_no         integer     NOT NULL CHECK (sequence_no > 0),
    order_id            text        NOT NULL,
    symbol              text        NOT NULL,
    side                text        NOT NULL CHECK (side IN ('buy', 'sell')),
    created_at          timestamptz NOT NULL,
    payload             jsonb       NOT NULL,
    PRIMARY KEY (run_id, sequence_no),
    UNIQUE (run_id, order_id)
);

CREATE TABLE IF NOT EXISTS mart.backtest_fill (
    run_id              uuid            NOT NULL REFERENCES mart.backtest_run(run_id) ON DELETE CASCADE,
    sequence_no         integer         NOT NULL CHECK (sequence_no > 0),
    fill_id             text            NOT NULL,
    order_id            text            NOT NULL,
    symbol              text            NOT NULL,
    side                text            NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity            numeric(38, 18) NOT NULL CHECK (quantity > 0),
    price               numeric(38, 12) NOT NULL CHECK (price > 0),
    commission          numeric(38, 12) NOT NULL CHECK (commission >= 0),
    fill_time           timestamptz     NOT NULL,
    payload             jsonb           NOT NULL,
    PRIMARY KEY (run_id, sequence_no),
    UNIQUE (run_id, fill_id)
);

CREATE INDEX IF NOT EXISTS idx_backtest_run_strategy_time
    ON mart.backtest_run (strategy_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_run_symbol_period
    ON mart.backtest_run (symbol, interval_code, period_start, period_end);

CREATE INDEX IF NOT EXISTS idx_backtest_signal_symbol_time
    ON mart.backtest_signal (symbol, signal_time);

CREATE INDEX IF NOT EXISTS idx_backtest_order_symbol_time
    ON mart.backtest_order (symbol, created_at);

CREATE INDEX IF NOT EXISTS idx_backtest_fill_symbol_time
    ON mart.backtest_fill (symbol, fill_time);
