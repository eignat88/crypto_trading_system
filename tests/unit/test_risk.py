from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.risk.risk_engine import RiskConfig, RiskEngine, RiskEvent, RiskLevel


class TestRiskEngine:
    def setup_method(self):
        self.config = RiskConfig()
        self.engine = RiskEngine(self.config)
        self.total_capital = Decimal("5000")

    def test_approved_trade(self):
        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is True
        assert result.risk_level == RiskLevel.LOW

    def test_position_size_exceeded(self):
        # Try to open position larger than 10%
        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.MAX_POSITION_SIZE in result.events

    def test_asset_exposure_exceeded(self):
        # Open multiple positions in same asset
        positions = {
            "pos1": {"symbol": "BTCUSDT", "value": Decimal("1000")},
            "pos2": {"symbol": "BTCUSDT", "value": Decimal("1000")},
        }

        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.5"),
            price=Decimal("1000"),
            current_balance=Decimal("2000"),
            current_positions=positions,
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.MAX_ASSET_EXPOSURE in result.events

    def test_capital_utilization_exceeded(self):
        # Fill up capital utilization
        positions = {f"pos{i}": {"symbol": f"COIN{i}", "value": Decimal("500")} for i in range(6)}

        result = self.engine.check_trade(
            symbol="NEWCOIN",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("500"),
            current_balance=Decimal("2000"),
            current_positions=positions,
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.MAX_CAPITAL_UTILIZATION in result.events

    def test_daily_loss_limit(self):
        # Set daily loss to exceed limit
        self.engine.daily_pnl = Decimal("-150")  # 3% of 5000

        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.DAILY_LOSS_LIMIT in result.events

    def test_weekly_loss_limit(self):
        # Set weekly loss to exceed limit
        self.engine.weekly_pnl = Decimal("-300")  # 6% of 5000

        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.WEEKLY_LOSS_LIMIT in result.events

    def test_drawdown_exceeded(self):
        # Set equity to show large drawdown
        self.engine.peak_equity = Decimal("5000")
        self.engine.current_equity = Decimal("4400")  # 12% drawdown

        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.MAX_DRAWDOWN in result.events

    def test_emergency_stop(self):
        self.engine.set_emergency_stop(True, "Test reason")

        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.EMERGENCY_STOP in result.events

    def test_stale_data(self):
        # Set last data time to 10 minutes ago
        self.engine.last_data_time = datetime.now(UTC) - timedelta(minutes=10)

        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("0.1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert RiskEvent.STALE_DATA in result.events

    def test_adjusted_quantity(self):
        # Try to open position larger than limit
        result = self.engine.check_trade(
            symbol="BTCUSDT",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("1000"),
            current_balance=Decimal("5000"),
            current_positions={},
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert result.adjusted_quantity is not None
        assert (
            result.adjusted_quantity * Decimal("1000")
            <= self.total_capital * self.config.max_position_size
        )

    def test_too_many_positions(self):
        # Fill up max positions
        positions = {f"pos{i}": {"symbol": f"COIN{i}", "value": Decimal("100")} for i in range(5)}

        result = self.engine.check_trade(
            symbol="NEWCOIN",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("100"),
            current_balance=Decimal("5000"),
            current_positions=positions,
            total_capital=self.total_capital,
        )
        assert result.approved is False
        assert result.risk_level == RiskLevel.MEDIUM

    def test_emergency_stop_activation(self):
        self.engine.set_emergency_stop(True, "Test")
        assert self.engine.is_emergency_stop is True

        self.engine.set_emergency_stop(False)
        assert self.engine.is_emergency_stop is False

    def test_consecutive_errors(self):
        for _ in range(5):
            self.engine.record_error()
        assert self.engine.is_emergency_stop is True

    def test_reset_daily(self):
        self.engine.daily_pnl = Decimal("-100")
        self.engine.reset_daily()
        assert self.engine.daily_pnl == Decimal("0")

    def test_max_risk_per_trade_uses_stop_loss(self):
        result = self.engine.check_trade(
            "BTCUSDT",
            "buy",
            Decimal("0.5"),
            Decimal("1000"),
            Decimal("5000"),
            {},
            self.total_capital,
            stop_loss_price=Decimal("900"),
        )
        assert not result.approved
        assert RiskEvent.MAX_RISK_PER_TRADE in result.events

    def test_insufficient_available_balance_is_rejected(self):
        result = self.engine.check_trade(
            "BTCUSDT",
            "buy",
            Decimal("0.1"),
            Decimal("1000"),
            Decimal("50"),
            {},
            self.total_capital,
        )
        assert RiskEvent.INSUFFICIENT_BALANCE in result.events

    def test_reducing_sell_does_not_increase_exposure(self):
        positions = {"btc": {"symbol": "BTCUSDT", "side": "long", "value": Decimal("1000")}}
        result = self.engine.check_trade(
            "BTCUSDT",
            "sell",
            Decimal("0.5"),
            Decimal("1000"),
            Decimal("0"),
            positions,
            self.total_capital,
        )
        assert result.approved

    def test_operational_failures_and_unknown_status_are_fail_closed(self):
        result = self.engine.check_trade(
            "BTCUSDT",
            "buy",
            Decimal("0.1"),
            Decimal("1000"),
            Decimal("5000"),
            {},
            self.total_capital,
            database_available=False,
            api_available=False,
            reconciliation_ok=False,
            order_statuses=["mystery"],
        )
        assert {
            RiskEvent.DATABASE_UNAVAILABLE,
            RiskEvent.API_UNAVAILABLE,
            RiskEvent.RECONCILIATION_FAILED,
            RiskEvent.UNKNOWN_ORDER_STATUS,
        } <= set(result.events)

    def test_emergency_stop_and_events_are_persisted_and_restored(self):
        class Store:
            state = None
            events = []

            def load_state(self):
                return self.state

            def save_state(self, state):
                self.state = state

            def save_event(self, event):
                self.events.append(event)

        store = Store()
        engine = RiskEngine(state_store=store)
        engine.set_emergency_stop(True, "operator")
        restored = RiskEngine(state_store=store)
        result = restored.check_trade(
            "BTCUSDT",
            "buy",
            Decimal("0.1"),
            Decimal("1000"),
            Decimal("5000"),
            {},
            self.total_capital,
        )
        assert restored.is_emergency_stop
        assert store.events[0]["event_type"] == RiskEvent.EMERGENCY_STOP.value
        assert not result.approved
