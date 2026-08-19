-- MART layer: analytical data for reporting

CREATE SCHEMA IF NOT EXISTS mart;

-- Daily performance
CREATE TABLE IF NOT EXISTS mart.daily_performance (
    id                  bigserial   PRIMARY KEY,
    report_date         date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    total_capital       numeric(38, 12) NOT NULL,
    daily_pnl           numeric(38, 12) NOT NULL DEFAULT 0,
    daily_pnl_pct       numeric(10, 6) NOT NULL DEFAULT 0,
    realized_pnl        numeric(38, 12) NOT NULL DEFAULT 0,
    unrealized_pnl      numeric(38, 12) NOT NULL DEFAULT 0,
    total_commission    numeric(38, 12) NOT NULL DEFAULT 0,
    trades_count        integer     NOT NULL DEFAULT 0,
    winning_trades      integer     NOT NULL DEFAULT 0,
    losing_trades       integer     NOT NULL DEFAULT 0,
    max_drawdown        numeric(10, 6) NOT NULL DEFAULT 0,
    current_drawdown    numeric(10, 6) NOT NULL DEFAULT 0,
    open_positions      integer     NOT NULL DEFAULT 0,
    capital_utilization numeric(10, 6) NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_daily_performance
        UNIQUE (report_date, exchange_name)
);

-- Strategy performance
CREATE TABLE IF NOT EXISTS mart.strategy_performance (
    id                  bigserial   PRIMARY KEY,
    strategy_name       text        NOT NULL,
    report_date         date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    total_pnl           numeric(38, 12) NOT NULL DEFAULT 0,
    total_pnl_pct       numeric(10, 6) NOT NULL DEFAULT 0,
    trades_count        integer     NOT NULL DEFAULT 0,
    winning_trades      integer     NOT NULL DEFAULT 0,
    losing_trades       integer     NOT NULL DEFAULT 0,
    win_rate            numeric(5, 4) NOT NULL DEFAULT 0,
    profit_factor       numeric(10, 4) NOT NULL DEFAULT 0,
    max_drawdown        numeric(10, 6) NOT NULL DEFAULT 0,
    sharpe_ratio        numeric(10, 4),
    avg_trade_pnl       numeric(38, 12) NOT NULL DEFAULT 0,
    avg_win             numeric(38, 12) NOT NULL DEFAULT 0,
    avg_loss            numeric(38, 12) NOT NULL DEFAULT 0,
    max_consecutive_losses integer NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_strategy_performance
        UNIQUE (strategy_name, report_date, exchange_name)
);

-- Asset performance
CREATE TABLE IF NOT EXISTS mart.asset_performance (
    id                  bigserial   PRIMARY KEY,
    symbol              text        NOT NULL,
    report_date         date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    total_pnl           numeric(38, 12) NOT NULL DEFAULT 0,
    total_pnl_pct       numeric(10, 6) NOT NULL DEFAULT 0,
    trades_count        integer     NOT NULL DEFAULT 0,
    winning_trades      integer     NOT NULL DEFAULT 0,
    losing_trades       integer     NOT NULL DEFAULT 0,
    max_position_size   numeric(38, 12) NOT NULL DEFAULT 0,
    avg_position_size   numeric(38, 12) NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_asset_performance
        UNIQUE (symbol, report_date, exchange_name)
);

-- Trade statistics
CREATE TABLE IF NOT EXISTS mart.trade_statistics (
    id                  bigserial   PRIMARY KEY,
    report_date         date        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    total_trades        integer     NOT NULL DEFAULT 0,
    total_volume        numeric(38, 12) NOT NULL DEFAULT 0,
    avg_trade_size      numeric(38, 12) NOT NULL DEFAULT 0,
    avg_holding_time    interval,
    total_commission    numeric(38, 12) NOT NULL DEFAULT 0,
    total_slippage      numeric(38, 12) NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_trade_statistics
        UNIQUE (report_date, exchange_name)
);

-- Drawdown history
CREATE TABLE IF NOT EXISTS mart.drawdown_history (
    id                  bigserial   PRIMARY KEY,
    timestamp           timestamptz NOT NULL,
    equity              numeric(38, 12) NOT NULL,
    peak_equity         numeric(38, 12) NOT NULL,
    drawdown            numeric(10, 6) NOT NULL,
    drawdown_pct        numeric(10, 6) NOT NULL,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Monthly returns
CREATE TABLE IF NOT EXISTS mart.monthly_returns (
    id                  bigserial   PRIMARY KEY,
    year_month          text        NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    total_pnl           numeric(38, 12) NOT NULL DEFAULT 0,
    total_pnl_pct       numeric(10, 6) NOT NULL DEFAULT 0,
    trades_count        integer     NOT NULL DEFAULT 0,
    win_rate            numeric(5, 4) NOT NULL DEFAULT 0,
    max_drawdown        numeric(10, 6) NOT NULL DEFAULT 0,
    created_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_mart_monthly_returns
        UNIQUE (year_month, exchange_name)
);

-- Risk dashboard
CREATE TABLE IF NOT EXISTS mart.risk_dashboard (
    id                  bigserial   PRIMARY KEY,
    snapshot_time       timestamptz NOT NULL,
    exchange_name       text        NOT NULL DEFAULT 'bybit',
    current_equity      numeric(38, 12) NOT NULL,
    peak_equity         numeric(38, 12) NOT NULL,
    current_drawdown    numeric(10, 6) NOT NULL,
    max_drawdown        numeric(10, 6) NOT NULL,
    daily_pnl           numeric(38, 12) NOT NULL,
    weekly_pnl          numeric(38, 12) NOT NULL,
    open_positions      integer     NOT NULL,
    capital_utilization numeric(10, 6) NOT NULL,
    risk_level          text        NOT NULL,
    emergency_stop      boolean     NOT NULL DEFAULT false,
    created_at          timestamptz NOT NULL DEFAULT now()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_mart_daily_performance_date
    ON mart.daily_performance (report_date DESC);

CREATE INDEX IF NOT EXISTS idx_mart_strategy_performance_date
    ON mart.strategy_performance (report_date DESC);

CREATE INDEX IF NOT EXISTS idx_mart_strategy_performance_name
    ON mart.strategy_performance (strategy_name, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_mart_asset_performance_date
    ON mart.asset_performance (report_date DESC);

CREATE INDEX IF NOT EXISTS idx_mart_asset_performance_symbol
    ON mart.asset_performance (symbol, report_date DESC);

CREATE INDEX IF NOT EXISTS idx_mart_drawdown_history_time
    ON mart.drawdown_history (timestamp DESC);

CREATE UNIQUE INDEX IF NOT EXISTS uq_mart_drawdown_history_timestamp
    ON mart.drawdown_history (timestamp);

CREATE INDEX IF NOT EXISTS idx_mart_monthly_returns_year
    ON mart.monthly_returns (year_month DESC);

CREATE INDEX IF NOT EXISTS idx_mart_risk_dashboard_time
    ON mart.risk_dashboard (snapshot_time DESC);
