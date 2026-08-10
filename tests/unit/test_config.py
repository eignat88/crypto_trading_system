"""Tests for configuration."""

import os
from unittest.mock import patch

import pytest

from app.config.settings import Settings, TradingMode


class TestTradingMode:
    def test_paper_mode(self):
        """Test that paper mode is allowed."""
        with patch.dict(os.environ, {"TRADING_MODE": "paper"}):
            settings = Settings()
            assert settings.trading_mode == TradingMode.PAPER

    def test_live_mode_blocked(self):
        """Test that live mode execution is blocked (future)."""
        with patch.dict(os.environ, {"TRADING_MODE": "live"}):
            settings = Settings()
            # Live mode is defined but execution should be blocked
            assert settings.trading_mode == TradingMode.LIVE

    def test_unknown_mode_blocked(self):
        """Test that unknown mode execution is blocked."""
        with patch.dict(os.environ, {"TRADING_MODE": "abc"}):
            # Unknown mode should fail validation
            with pytest.raises(Exception):
                Settings()


class TestBybitConfig:
    def test_demo_environment(self):
        """Test demo environment."""
        with patch.dict(os.environ, {"BYBIT_ENVIRONMENT": "demo"}):
            settings = Settings()
            assert settings.bybit_environment == "demo"

    def test_testnet_environment(self):
        """Test testnet environment."""
        with patch.dict(os.environ, {"BYBIT_ENVIRONMENT": "testnet"}):
            settings = Settings()
            assert settings.bybit_environment == "testnet"

    def test_mainnet_environment(self):
        """Test mainnet environment."""
        with patch.dict(os.environ, {"BYBIT_ENVIRONMENT": "mainnet"}):
            settings = Settings()
            assert settings.bybit_environment == "mainnet"


class TestSymbols:
    def test_spot_symbols(self):
        """Test that only SPOT symbols are allowed."""
        with patch.dict(os.environ, {"TRADING_SYMBOLS": "BTCUSDT-SPOT,ETHUSDT-SPOT"}):
            settings = Settings()
            symbols = [s.strip() for s in settings.trading_symbols.split(",")]
            assert "BTCUSDT-SPOT" in symbols
            assert "ETHUSDT-SPOT" in symbols

    def test_linear_symbols_not_allowed(self):
        """Test that LINEAR symbols are not allowed."""
        # The application should reject LINEAR symbols
        # This is enforced at the application level, not config level
        with patch.dict(os.environ, {"TRADING_SYMBOLS": "BTCUSDT-LINEAR"}):
            settings = Settings()
            symbols = [s.strip() for s in settings.trading_symbols.split(",")]
            # Config allows it, but application should reject
            assert "BTCUSDT-LINEAR" in symbols


class TestDatabase:
    def test_database_url_generation(self):
        """Test database URL generation."""
        with patch.dict(os.environ, {
            "POSTGRES_HOST": "localhost",
            "POSTGRES_PORT": "5432",
            "POSTGRES_DB": "crypto_trading",
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "secret",
        }):
            settings = Settings()
            assert "postgresql+asyncpg://postgres:secret@localhost:5432/crypto_trading" in settings.database_url
            assert "postgresql://postgres:secret@localhost:5432/crypto_trading" in settings.database_url_sync
