from datetime import UTC, datetime
from decimal import Decimal

from app.indicators.market_regime import MarketRegime
from app.strategies.trend_dca import DCAConfig, TrendDCAStrategy


class TestTrendDCAStrategy:
    def setup_method(self):
        self.strategy = TrendDCAStrategy(symbols=["BTCUSDT"])

    def test_entry_conditions_met(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("105"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "ema_200": Decimal("100"),
            "ema_50": Decimal("102"),
            "rsi": Decimal("40"),
            "regime": MarketRegime.TREND_UP,
            "volatility": Decimal("0.5"),
        }

        portfolio_state = {
            "has_position": False,
            "capital": Decimal("5000"),
        }

        signal = self.strategy.should_enter(candle, indicators, portfolio_state)
        assert signal is not None
        assert signal.action == "open_long"
        assert signal.symbol == "BTCUSDT"
        assert signal.quantity * signal.price == Decimal("125")
        assert signal.stop_loss == signal.price * Decimal("0.85")

    def test_entry_no_position(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("105"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "ema_200": Decimal("100"),
            "ema_50": Decimal("102"),
            "rsi": Decimal("40"),
            "regime": MarketRegime.TREND_UP,
        }

        portfolio_state = {
            "has_position": True,  # Already has position
            "capital": Decimal("5000"),
        }

        signal = self.strategy.should_enter(candle, indicators, portfolio_state)
        assert signal is None

    def test_entry_wrong_regime(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("105"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "ema_200": Decimal("100"),
            "ema_50": Decimal("102"),
            "rsi": Decimal("40"),
            "regime": MarketRegime.TREND_DOWN,  # Wrong regime
        }

        portfolio_state = {
            "has_position": False,
            "capital": Decimal("5000"),
        }

        signal = self.strategy.should_enter(candle, indicators, portfolio_state)
        assert signal is None

    def test_entry_rsi_too_high(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("105"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "ema_200": Decimal("100"),
            "ema_50": Decimal("102"),
            "rsi": Decimal("55"),  # Too high
            "regime": MarketRegime.TREND_UP,
        }

        portfolio_state = {
            "has_position": False,
            "capital": Decimal("5000"),
        }

        signal = self.strategy.should_enter(candle, indicators, portfolio_state)
        assert signal is None

    def test_exit_take_profit(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("110"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "regime": MarketRegime.TREND_UP,
        }

        position = {
            "entry_price": Decimal("100"),
            "side": "long",
            "quantity": Decimal("10"),
            "unrealized_pnl_pct": Decimal("0.10"),  # 10% profit
        }

        signal = self.strategy.should_exit(candle, indicators, position)
        assert signal is not None
        assert signal.action == "close"
        assert "Take profit" in signal.reason

    def test_exit_regime_change(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("95"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "regime": MarketRegime.TREND_DOWN,
        }

        position = {
            "entry_price": Decimal("100"),
            "side": "long",
            "quantity": Decimal("10"),
            "unrealized_pnl_pct": Decimal("-0.05"),
        }

        signal = self.strategy.should_exit(candle, indicators, position)
        assert signal is not None
        assert signal.action == "close"
        assert "Regime changed" in signal.reason

    def test_exit_max_holding_period(self):
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("100"),
            "open_time": datetime.now(UTC),
        }

        indicators = {
            "regime": MarketRegime.TREND_UP,
        }

        position = {
            "entry_price": Decimal("100"),
            "side": "long",
            "quantity": Decimal("10"),
            "unrealized_pnl_pct": Decimal("0"),
            "holding_periods": 100,  # Max holding period
        }

        signal = self.strategy.should_exit(candle, indicators, position)
        assert signal is not None
        assert signal.action == "close"
        assert "Max holding period" in signal.reason

    def test_trailing_stop_uses_high_watermark(self):
        position = {
            "entry_price": Decimal("100"),
            "side": "long",
            "quantity": Decimal("1"),
            "unrealized_pnl_pct": Decimal("0.04"),
        }
        indicators = {"regime": MarketRegime.TREND_UP}
        now = datetime.now(UTC)

        assert self.strategy.should_exit(
            {"symbol": "BTCUSDT", "close": Decimal("104"), "open_time": now},
            indicators,
            position,
        ) is None
        signal = self.strategy.should_exit(
            {"symbol": "BTCUSDT", "close": Decimal("101.9"), "open_time": now},
            indicators,
            {**position, "unrealized_pnl_pct": Decimal("0.019")},
        )
        assert signal is not None
        assert signal.reason == "Trailing stop hit"

    def test_dca_level_advances_only_after_fill(self):
        now = datetime.now(UTC)
        candle = {
            "symbol": "BTCUSDT",
            "close": Decimal("96"),
            "open_time": now,
        }
        position = {
            "entry_price": Decimal("100"),
            "quantity": Decimal("1"),
            "capital": Decimal("5000"),
        }

        first = self.strategy.should_add_dca(candle, {}, position)
        repeated = self.strategy.should_add_dca(candle, {}, position)

        assert first is not None
        assert repeated is not None
        assert first.metadata["dca_level"] == 1
        assert repeated.metadata["dca_level"] == 1


class TestDCAConfig:
    def test_default_config(self):
        config = DCAConfig()
        assert config.base_order_pct == Decimal("0.25")
        assert config.take_profit_pct == Decimal("0.05")
        assert config.trailing_stop_activation == Decimal("0.03")
