# Crypto Trading System

Automated cryptocurrency trading system with NautilusTrader integration.

## Current Status

**Last updated: 2026-08-19**

The current audited development plan is
[`plan/DEVELOPMENT_PLAN_2026-08-19.md`](plan/DEVELOPMENT_PLAN_2026-08-19.md).

The project is in the backtest/walk-forward and sealed independent-validation
phase. The prospective `Breakout Retest v2` holdout covers BTCUSDT and ETHUSDT
1h candles from 2026-08-10 and remains performance-sealed until
2027-02-06T00:00:00Z.

- ✅ RAW → DDS, versioned indicators/regimes, backtest, Risk Engine and CI are implemented.
- ✅ Python 3.12 unit and PostgreSQL 17 integration baselines are enforced in CI.
- ✅ Sealed holdout pipeline with incremental updates (`scripts/update_holdout_data.py`)
- ✅ Paper runtime composition is available with fail-closed preflight, PostgreSQL
  recovery, indicator warmup, the shared RiskEngine and graceful checkpointing.
- 🚧 A long-running market subscription and reconciliation gate remain required
  before an operational paper pilot.
- ⛔ Live trading blocked: the paper execution path exists, but live order management,
  exchange reconciliation, and operational monitoring are not implemented.

Do not run strategy performance against the prospective holdout before its
configured unlock time.

## Requirements

- Python 3.12 (the project metadata permits newer compatible versions, while CI and
  the reproducible local baseline use 3.12)
- PostgreSQL 14+
- NautilusTrader

## Installation

### Windows PowerShell

```powershell
# Clone repository
git clone https://github.com/eignat88/crypto_trading_system.git
cd crypto_trading_system

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Upgrade pip
python -m pip install --upgrade pip

# Install the application and test/tooling baseline
python -m pip install -e ".[dev]"
```

### Linux/macOS

```bash
# Clone repository
git clone https://github.com/eignat88/crypto_trading_system.git
cd crypto_trading_system

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Upgrade pip
python -m pip install --upgrade pip

# Install the application and test/tooling baseline
python -m pip install -e ".[dev]"
```

## Configuration

```powershell
# Copy environment file
Copy-Item .env.example .env

# Edit .env with your settings
notepad .env
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TRADING_MODE` | Trading mode (paper/live) | `paper` |
| `BYBIT_ENVIRONMENT` | Bybit environment (demo/testnet/mainnet) | `demo` |
| `TRADING_SYMBOLS` | Trading symbols | `BTCUSDT-SPOT,ETHUSDT-SPOT` |
| `POSTGRES_HOST` | PostgreSQL host | `localhost` |
| `POSTGRES_PORT` | PostgreSQL port | `5432` |
| `POSTGRES_DB` | PostgreSQL database | `crypto_trading` |
| `POSTGRES_USER` | PostgreSQL user | `postgres` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `` |
| `LOG_LEVEL` | Logging level | `INFO` |

## Database Setup

```powershell
# Check database connection
python .\scripts\check_database.py

# Apply every pending migration from database/migrations/
python .\scripts\migrate_database.py

# Optional: target an isolated database explicitly
python .\scripts\migrate_database.py --database-url $env:TEST_DATABASE_URL
```

## Run the paper application

Apply migrations first, then start the only paper composition root:

```bash
export TRADING_MODE=paper
python scripts/run_paper.py
```

Startup checks paper-only mode, exchange/symbol/capital/risk configuration, the
PostgreSQL connection, the migration journal and repository restore access. `live`,
unknown modes, an unavailable database or missing migrations block startup. State is
restored before market warmup; fewer than 200 valid closed 1h candles for any configured
symbol keeps the runtime observable but disables strategy orders. SIGINT/SIGTERM stops
new events, completes the active candle, writes runtime and PnL checkpoints and closes
database connections. Orders, fills and snapshots use idempotent persistence, so restart
continues from the saved market sequence rather than replaying confirmed work.

## Bybit Connection Check

```powershell
# Test Bybit connection
python .\scripts\check_bybit_connection.py
```

Expected output:
```
============================================================
Bybit Connection Test
============================================================

Environment: demo
Symbols: ['BTCUSDT-SPOT', 'ETHUSDT-SPOT']

Connecting to Bybit...

BYBIT connection: OK

Total instruments loaded: 2

BTCUSDT-SPOT.BYBIT: FOUND
  Base currency: BTC
  Quote currency: USDT
  Lot size: 0.000001
  Tick size: 0.01

ETHUSDT-SPOT.BYBIT: FOUND
  Base currency: ETH
  Quote currency: USDT
  Lot size: 0.00001
  Tick size: 0.01

Market data: RECEIVED (if subscribed)

Trading orders submitted: 0

============================================================
```

## Collect Market Data

```powershell
# Start collecting market data
python .\scripts\collect_market_data.py
```

Press `Ctrl+C` to stop.

## Tests

```powershell
# Run all tests
pytest -q

# Run unit tests only
pytest tests/unit/ -q

# Run integration tests (requires Bybit connection)
pytest -m integration -q

# Run with coverage
pytest --cov=app --cov-report=html
```

## Project Structure

```
crypto_trading_system/
├── app/
│   ├── config/         # Configuration
│   ├── collectors/     # Market data collectors
│   ├── exchange/       # Exchange adapters
│   ├── database/       # Database connection
│   ├── indicators/     # Technical indicators
│   ├── strategies/     # Trading strategies
│   ├── risk/           # Risk engine
│   ├── execution/      # Order execution
│   ├── backtest/       # Backtesting engine
│   ├── monitoring/     # Monitoring
│   └── reporting/      # Reporting
├── database/migrations/ # Canonical ordered SQL migrations
├── sql/                # Non-migration diagnostic SQL
├── scripts/            # Utility scripts
├── tests/              # Tests
└── docs/               # Documentation
```

## Architecture

```
Bybit
  │
  ▼
NautilusTrader Adapter
  │
  ▼
Market Data (RAW)
  │
  ▼
DDS (Normalized)
  │
  ▼
Indicators
  │
  ▼
Market Regime
  │
  ▼
Strategy
  │
  ▼
Signal
  │
  ▼
Risk Engine
```

## License

MIT
