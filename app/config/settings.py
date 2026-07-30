from pydantic_settings import BaseSettings
from pydantic import Field
from enum import Enum


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class ExchangeName(str, Enum):
    BYBIT = "bybit"


class Settings(BaseSettings):
    # Exchange
    exchange_name: ExchangeName = ExchangeName.BYBIT
    exchange_api_key: str = Field(default="", description="Exchange API key")
    exchange_api_secret: str = Field(default="", description="Exchange API secret")

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://user:password@localhost:5432/crypto_trading",
        description="Async database URL",
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg2://user:password@localhost:5432/crypto_trading",
        description="Sync database URL for migrations",
    )

    # Trading Mode
    trading_mode: TradingMode = TradingMode.PAPER

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
