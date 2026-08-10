from enum import StrEnum

from pydantic import Field
from pydantic_settings import BaseSettings


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class ExchangeName(StrEnum):
    BYBIT = "bybit"


class Settings(BaseSettings):
    # Trading Mode
    trading_mode: TradingMode = TradingMode.PAPER

    # Bybit Configuration
    bybit_environment: str = Field(default="demo", description="Bybit environment: demo, testnet, mainnet")
    trading_symbols: str = Field(default="BTCUSDT-SPOT,ETHUSDT-SPOT", description="Trading symbols")

    # Exchange API (for future live trading)
    exchange_api_key: str = Field(default="", description="Exchange API key")
    exchange_api_secret: str = Field(default="", description="Exchange API secret")

    # PostgreSQL Configuration
    postgres_host: str = Field(default="localhost", description="PostgreSQL host")
    postgres_port: int = Field(default=5432, description="PostgreSQL port")
    postgres_db: str = Field(default="crypto_trading", description="PostgreSQL database")
    postgres_user: str = Field(default="postgres", description="PostgreSQL user")
    postgres_password: str = Field(default="", description="PostgreSQL password")

    @property
    def database_url(self) -> str:
        """Async database URL for SQLAlchemy."""
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    @property
    def database_url_sync(self) -> str:
        """Sync database URL for psycopg."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # Risk Limits
    max_risk_per_trade: float = Field(default=0.005, ge=0.0, le=1.0)
    max_position_size: float = Field(default=0.10, ge=0.0, le=1.0)
    max_asset_exposure: float = Field(default=0.25, ge=0.0, le=1.0)
    max_capital_utilization: float = Field(default=0.60, ge=0.0, le=1.0)
    daily_loss_limit: float = Field(default=0.02, ge=0.0, le=1.0)
    weekly_loss_limit: float = Field(default=0.05, ge=0.0, le=1.0)
    max_drawdown: float = Field(default=0.10, ge=0.0, le=1.0)

    # Paper Trading
    paper_initial_balance: float = Field(default=5000.0, gt=0.0)

    # Logging
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/trading.log")

    # Monitoring
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


settings = Settings()
