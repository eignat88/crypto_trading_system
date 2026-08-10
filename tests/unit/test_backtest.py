from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.backtest.backtest_engine import BacktestConfig, BacktestEngine
from app.backtest.commission_model import CommissionModel
from app.backtest.portfolio import Portfolio
from app.backtest.slippage_model import SlippageModel
from app.risk.risk_engine import RiskConfig, RiskEngine
from app.strategies.base_strategy import Signal
from app.strategies.trend_dca import TrendDCAStrategy


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
            timestamp=datetime.now(UTC),
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
            timestamp=datetime.now(UTC),
        )
        assert result is False
        assert not self.portfolio.has_position("BTCUSDT")

    def test_close_position(self):
        self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(UTC),
        )

        pnl = self.portfolio.close_position(
            symbol="BTCUSDT",
            price=Decimal("110"),
            timestamp=datetime.now(UTC),
        )

        assert pnl is not None
        assert pnl == Decimal("100")
        assert not self.portfolio.has_position("BTCUSDT")
        assert len(self.portfolio.trade_history) == 2

    def test_update_positions(self):
        self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(UTC),
        )

        self.portfolio.update_positions(
            {"BTCUSDT": Decimal("110")},
            datetime.now(UTC),
        )

        position = self.portfolio.get_position("BTCUSDT")
        assert position.unrealized_pnl == Decimal("100")
        assert self.portfolio.total_equity == Decimal("5100")

    def test_dca_merges_quantity_and_weighted_entry(self):
        now = datetime.now(UTC)
        self.portfolio.open_position(
            "BTCUSDT", "long", Decimal("100"), Decimal("10"), now,
            stop_loss=Decimal("90"), take_profit=Decimal("120"),
        )
        self.portfolio.open_position(
            "BTCUSDT", "long", Decimal("80"), Decimal("10"), now,
        )

        position = self.portfolio.get_position("BTCUSDT")
        assert len(self.portfolio.positions) == 1
        assert position.quantity == Decimal("20")
        assert position.entry_price == Decimal("90")
        assert position.stop_loss == Decimal("90")
        assert position.take_profit == Decimal("120")

    def test_spot_portfolio_rejects_short(self):
        opened = self.portfolio.open_position(
            "BTCUSDT", "short", Decimal("100"), Decimal("10"),
            datetime.now(UTC),
        )
        assert opened is False

    def test_check_stops(self):
        self.portfolio.open_position(
            symbol="BTCUSDT",
            side="long",
            price=Decimal("100"),
            quantity=Decimal("10"),
            timestamp=datetime.now(UTC),
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
        )

        symbols = self.portfolio.check_stops({"BTCUSDT": Decimal("94")})
        assert "BTCUSDT" in symbols

        symbols = self.portfolio.check_stops({"BTCUSDT": Decimal("111")})
        assert "BTCUSDT" in symbols

    def test_intrabar_stop_uses_low_and_stop_level(self):
        self.portfolio.open_position(
            "BTCUSDT", "long", Decimal("100"), Decimal("10"),
            datetime.now(UTC), stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )

        events = self.portfolio.check_intrabar_exits({
            "BTCUSDT": {
                "open": Decimal("100"),
                "high": Decimal("105"),
                "low": Decimal("94"),
            }
        })

        assert len(events) == 1
        assert events[0].reason == "Stop-loss hit"
        assert events[0].reference_price == Decimal("95")

    def test_intrabar_stop_gap_down_uses_open(self):
        self.portfolio.open_position(
            "BTCUSDT", "long", Decimal("100"), Decimal("10"),
            datetime.now(UTC), stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )

        events = self.portfolio.check_intrabar_exits({
            "BTCUSDT": {
                "open": Decimal("90"),
                "high": Decimal("96"),
                "low": Decimal("89"),
            }
        })

        assert len(events) == 1
        assert events[0].reason == "Stop-loss hit on gap"
        assert events[0].reference_price == Decimal("90")

    def test_intrabar_take_profit_uses_high_and_target_level(self):
        self.portfolio.open_position(
            "BTCUSDT", "long", Decimal("100"), Decimal("10"),
            datetime.now(UTC), stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )

        events = self.portfolio.check_intrabar_exits({
            "BTCUSDT": {
                "open": Decimal("100"),
                "high": Decimal("111"),
                "low": Decimal("99"),
            }
        })

        assert len(events) == 1
        assert events[0].reason == "Take-profit hit"
        assert events[0].reference_price == Decimal("110")

    def test_intrabar_ambiguous_bar_uses_conservative_stop_first(self):
        self.portfolio.open_position(
            "BTCUSDT", "long", Decimal("100"), Decimal("10"),
            datetime.now(UTC), stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )

        events = self.portfolio.check_intrabar_exits({
            "BTCUSDT": {
                "open": Decimal("100"),
                "high": Decimal("111"),
                "low": Decimal("94"),
            }
        })

        assert len(events) == 1
        assert events[0].reason == "Stop-loss hit"
        assert events[0].reference_price == Decimal("95")


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
        candles = []
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
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
        assert result.total_trades == 1
        assert result.portfolio.balance != Decimal("5000")

    def test_dataclass_signal_preserves_stop_levels(self):
        now = datetime.now(UTC)
        candle = {
            "open_time": now, "symbol": "BTCUSDT", "open": Decimal("100"),
            "high": Decimal("100"), "low": Decimal("100"), "close": Decimal("100"),
            "volume": Decimal("1"),
        }
        risk = RiskEngine(RiskConfig(max_position_size=Decimal("1")))
        engine = BacktestEngine(BacktestConfig(), risk_engine=risk)

        signal = Signal(
            "open_long", "BTCUSDT", Decimal("100"), Decimal("1"), now,
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        engine._process_signal(signal, candle, now)

        position = engine.portfolio.get_position("BTCUSDT")
        assert position.stop_loss == Decimal("95")
        assert position.take_profit == Decimal("110")

    def test_risk_engine_rejects_trade(self):
        risk = RiskEngine(RiskConfig(max_position_size=Decimal("0.01")))
        risk.set_emergency_stop(True, "test")
        engine = BacktestEngine(BacktestConfig(), risk_engine=risk)
        candle = {
            "open_time": datetime.now(UTC), "symbol": "BTCUSDT",
            "close": Decimal("100"),
        }

        engine.run(
            [candle],
            lambda *_: [{"action": "buy", "symbol": "BTCUSDT", "quantity": Decimal("1")}],
        )
        assert engine.portfolio.trade_history == []

    def test_intrabar_stop_executes_from_stop_reference_not_close(self):
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            {
                "open_time": base_time,
                "symbol": "BTCUSDT",
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
            },
            {
                "open_time": base_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("94"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
            },
        ]

        def strategy(candle, portfolio, state):
            if not portfolio.has_position("BTCUSDT"):
                return Signal(
                    "open_long", "BTCUSDT", Decimal("100"), Decimal("1"),
                    candle["open_time"], stop_loss=Decimal("95"), take_profit=Decimal("110"),
                )
            return None

        result = self.engine.run(candles, strategy)
        sell_order = [order for order in result.orders if order.side == "sell"][0]
        sell_fill = [fill for fill in result.fills if fill.side == "sell"][0]

        assert sell_order.requested_price == Decimal("95")
        assert sell_fill.price < Decimal("95")
        assert result.signals[-1].reason == "Stop-loss hit"
        assert result.signals[-1].parameters_version == "backtest_engine_v1"
        assert result.total_trades == 1

    def test_intrabar_take_profit_executes_from_target_reference(self):
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        candles = [
            {
                "open_time": base_time,
                "symbol": "BTCUSDT",
                "open": Decimal("100"),
                "high": Decimal("101"),
                "low": Decimal("99"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
            },
            {
                "open_time": base_time + timedelta(hours=1),
                "symbol": "BTCUSDT",
                "open": Decimal("100"),
                "high": Decimal("111"),
                "low": Decimal("99"),
                "close": Decimal("100"),
                "volume": Decimal("1000"),
            },
        ]

        def strategy(candle, portfolio, state):
            if not portfolio.has_position("BTCUSDT"):
                return Signal(
                    "open_long", "BTCUSDT", Decimal("100"), Decimal("1"),
                    candle["open_time"], stop_loss=Decimal("95"), take_profit=Decimal("110"),
                )
            return None

        result = self.engine.run(candles, strategy)
        sell_order = [order for order in result.orders if order.side == "sell"][0]
        sell_fill = [fill for fill in result.fills if fill.side == "sell"][0]

        assert sell_order.requested_price == Decimal("110")
        assert sell_fill.price < Decimal("110")
        assert result.signals[-1].reason == "Take-profit hit"
        assert result.total_trades == 1

    def test_trend_dca_runs_through_risk_orders_and_fills(self):
        base_time = datetime(2024, 1, 1, tzinfo=UTC)
        prices = [Decimal("100"), Decimal("96"), Decimal("92"), Decimal("86"), Decimal("105")]
        candles = []
        for index, close in enumerate(prices):
            candles.append({
                "open_time": base_time + timedelta(hours=index),
                "symbol": "BTCUSDT",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": Decimal("1000"),
                "indicators": {
                    "ema_200": Decimal("90"),
                    "ema_50": Decimal("95"),
                    "rsi": Decimal("40"),
                    "regime": "TREND_UP",
                    "volatility": Decimal("0.2"),
                },
            })

        engine = BacktestEngine(BacktestConfig(initial_balance=Decimal("5000")))
        result = engine.run(candles, TrendDCAStrategy(["BTCUSDT"]))

        buy_fills = [fill for fill in result.fills if fill.side == "buy"]
        assert len(buy_fills) == 3
        assert len(result.risk_decisions) == len(result.orders)
        assert all(decision.approved for decision in result.risk_decisions)
        assert sum(fill.price * fill.quantity for fill in buy_fills) <= Decimal("505")
        assert result.total_trades == 1
        assert all(
            signal.parameters_version
            for signal in result.signals
            if signal.strategy == "TrendDCA"
        )

    def test_trend_dca_does_not_add_in_range_regime(self):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        strategy = TrendDCAStrategy(["BTCUSDT"])
        strategy.dca_levels["BTCUSDT"] = 0

        signal = strategy.should_add_dca(
            {
                "open_time": now,
                "symbol": "BTCUSDT",
                "close": Decimal("96"),
            },
            {
                "regime": "RANGE",
                "rsi": Decimal("30"),
            },
            {
                "entry_price": Decimal("100"),
                "quantity": Decimal("1"),
                "capital": Decimal("5000"),
            },
        )

        assert signal is None

    def test_trend_dca_exit_signal_has_complete_audit_fields(self):
        now = datetime(2024, 1, 1, tzinfo=UTC)
        strategy = TrendDCAStrategy(["BTCUSDT"])
        indicators = {
            "regime": "TREND_DOWN",
            "rsi": Decimal("50"),
        }

        signal = strategy.should_exit(
            {
                "open_time": now,
                "symbol": "BTCUSDT",
                "close": Decimal("95"),
                "high": Decimal("96"),
                "low": Decimal("94"),
            },
            indicators,
            {
                "entry_price": Decimal("100"),
                "quantity": Decimal("1"),
                "unrealized_pnl_pct": Decimal("-0.05"),
                "holding_periods": 1,
            },
        )

        assert signal is not None
        assert signal.strategy == "TrendDCA"
        assert signal.parameters_version == "trend_dca_v1"
        assert signal.regime == "TREND_DOWN"
        assert signal.indicators == indicators

    def test_short_signal_is_not_supported(self):
        now = datetime.now(UTC)
        candle = {
            "open_time": now,
            "symbol": "BTCUSDT",
            "close": Decimal("100"),
        }

        try:
            self.engine._process_signal(
                {
                    "action": "open_short",
                    "symbol": "BTCUSDT",
                    "price": Decimal("100"),
                    "quantity": Decimal("1"),
                },
                candle,
                now,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("open_short must be rejected by the spot backtest")
