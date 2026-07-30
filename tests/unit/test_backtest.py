import pytest
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from app.backtest.portfolio import Portfolio
from app.backtest.commission_model import CommissionModel, CommissionConfig
from app.backtest.slippage_model import SlippageModel, SlippageConfig
from app.backtest.backtest_engine import BacktestEngine, BacktestConfig


class TestPortfolio:
    def setup_method(self):
        self.portfolio = Portfolio(initial_balance=Decimal("5000"))

    def test_initial_state(self):
        assert self.portfolio.balance == Decimal("5000")
        assert self.portfolio.total_equity == Decimal("5000")
        assert len(self.portfolio.positions) == 0

    def test_open_position(self):
        result = self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(timezone.utc),
        )
        assert result is True
        assert self.portfolio.has_position("BTCUSDT")
        assert self.portfolio.balance < Decimal("5000")

    def test_open_position_insufficient_balance(self):
        result = self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("1000"),
            quantity=Decimal("100"),
            timestamp=datetime.now(timezone.utc),
        )
        assert result is False
        assert not self.portfolio.has_position("BTCUSDT")

    def test_close_position(self):
        self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(timezone.utc),
        )
        
        pnl = self.portfolio.close_position(
            symbol="BTCUSDT",
            price=Decimal("110"),
            timestamp=datetime.now(timezone.utc),
        )
        
        assert pnl is not None
        assert pnl == Decimal("100")  # (110 - 100) * 10
        assert not self.portfolio.has_position("BTCUSDT")
        assert len(self.portfolio.trade_history) == 2  # open + close

    def test_update_positions(self):
        self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(timezone.utc),
        )
        
        self.portfolio.update_positions(
            {"BTCUSDT": Decimal("110")},
            datetime.now(timezone.utc),
        )
        
        position = self.portfolio.get_position("BTCUSDT")
        assert position.unrealized_pnl == Decimal("100")

    def test_check_stops(self):
        self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(timezone.utc),
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
        )
        
        # Check stop-loss
        symbols = self.portfolio.check_stops({"BTCUSDT": Decimal("94")})
        assert "BTCUSDT" in symbols
        
        # Check take-profit
        symbols = self.portfolio.check_stops({"BTCUSDT": Decimal("111")})
        assert "BTCUSDT" in symbols


class TestCommissionModel:
    def setup_method(self):
        self.model = CommissionModel()

    def test_calculate_commission(self):
        commission = self.model.calculate_commission(
            quantity=Decimal("10"),
            price=Decimal("100"),
        )
        assert commission == Decimal("10") * Decimal("100") * Decimal("0.001")

    def test_minimum_fee(self):
        commission = self.model.calculate_commission(
            quantity=Decimal("0.001"),
            price=Decimal("100"),
        )
        assert commission == Decimal("0.0001")


class TestSlippageModel:
    def setup_method(self):
        self.model = SlippageModel(seed=42)

    def test_buy_slippage(self):
        price = self.model.calculate_slippage(
            price=Decimal("100"),
            quantity=Decimal("10"),
            is_buy=True,
        )
        assert price > Decimal("100")

    def test_sell_slippage(self):
        price = self.model.calculate_slippage(
            price=Decimal("100"),
            quantity=Decimal("10"),
            is_buy=False,
        )
        assert price < Decimal("100")


class TestBacktestEngine:
    def setup_method(self):
        self.engine = BacktestEngine(
            BacktestConfig(initial_balance=Decimal("5000"))
        )

    def test_simple_buy_and_hold(self):
        # Create simple uptrend data
        candles = []
        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        for i in range(100):
            candles.append({
                "open_time": base_time + timedelta(hours=i),
                "symbol": "BTCUSDT",
                "open": Decimal("100") + Decimal(str(i)),
                "high": Decimal("101") + Decimal(str(i)),
                "low": Decimal("99") + Decimal(str(i)),
                "close": Decimal("100") + Decimal(str(i)),
                "volume": Decimal("1000"),
            })

        def buy_and_hold_strategy(candle, portfolio, state):
            if not portfolio.has_position("BTCUSDT"):
                return [{"action": "buy", "symbol": "BTCUSDT", "quantity": Decimal("10")}]
            return None

        result = self.engine.run(candles, buy_and_hold_strategy)
        assert result.total_trades == 1  # Only the buy
        # Balance should be different from initial (could be higher or lower depending on slippage)
        assert result.portfolio.balance != Decimal("5000")
