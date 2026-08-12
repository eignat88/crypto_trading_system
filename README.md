# Crypto Trading System

Automated cryptocurrency trading system with NautilusTrader integration.

## Current Status

The project is in the backtest/walk-forward and sealed independent-validation
phase. The prospective `Breakout Retest v2` holdout covers BTCUSDT and ETHUSDT
1h candles from 2026-08-10 and remains performance-sealed until
2027-02-06T00:00:00Z.

- RAW -> DDS, versioned indicators/regimes, backtest, Risk Engine and CI are implemented.
- `scripts/update_holdout_data.py` maintains only closed holdout candles and data health.
- Paper Exchange, restart recovery, reconciliation and production monitoring are not implemented.
- Paper and live trading remain blocked.

Do not run strategy performance against the prospective holdout before its
configured unlock time.

## Requirements

- Python 3.12+
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

# Install dependencies
pip install -e .
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

# Install dependencies
pip install -e .
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

# Apply migrations
psql -U postgres -d crypto_trading -f .\sql\001_create_raw.sql
psql -U postgres -d crypto_trading -f .\sql\002_create_dds.sql
psql -U postgres -d crypto_trading -f .\sql\003_create_mart.sql
psql -U postgres -d crypto_trading -f .\sql\007_create_raw_bybit.sql
```

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
├── sql/                # SQL migrations
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
