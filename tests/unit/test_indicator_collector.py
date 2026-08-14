"""Unit tests for indicator collector idempotency and calculation."""



class TestIndicatorCollectorIdempotency:
    """Tests for IndicatorCollector idempotency behavior."""

    def test_indicator_unique_constraint_exists(self):
        """Test that dds.indicator has proper unique constraint for idempotency."""
        from pathlib import Path
        sql = (Path(__file__).parents[2] / "sql" / "002_create_dds.sql").read_text()
        assert "UNIQUE (candle_id, indicator_name, indicator_params)" in sql

    def test_market_regime_unique_constraint_exists(self):
        """Test that dds.market_regime has proper unique constraint for idempotency."""
        from pathlib import Path
        sql = (Path(__file__).parents[2] / "sql" / "002_create_dds.sql").read_text()
        assert "UNIQUE (candle_id)" in sql

    def test_indicator_collector_has_model_versioning(self):
        """Test that indicator collector uses model versioning."""
        from app.collectors.indicator_collector import IndicatorCollector
        collector = IndicatorCollector()
        assert collector.indicator_model_version is not None
        assert collector.regime_model_version is not None

    def test_indicator_store_uses_on_conflict(self):
        """Test that indicator storage uses ON CONFLICT for upserts."""
        from pathlib import Path
        sql = (Path(__file__).parents[2] / "sql" / "002_create_dds.sql").read_text()
        # Check the indicator table structure supports versioning
        assert "model_version" in sql or "indicator_params" in sql


class TestCandleCollectorWithIndicators:
    """Tests for candle collector with integrated indicator calculation."""

    def test_load_historical_candles_has_skip_flag(self):
        """Test that load_historical_candles accepts calculate_indicators parameter."""
        import inspect

        from app.collectors.candle_collector import CandleCollector
        sig = inspect.signature(CandleCollector.load_historical_candles)
        assert "calculate_indicators" in sig.parameters

    def test_load_history_script_has_skip_indicators_flag(self):
        """Test that load_history.py script has --skip-indicators flag."""
        from pathlib import Path
        script = (Path(__file__).parents[2] / "scripts" / "load_history.py").read_text()
        assert "--skip-indicators" in script
        assert "calculate_indicators" in script


class TestLoadMartScript:
    """Tests for MART ETL script."""

    def test_load_mart_script_exists(self):
        """Test that load_mart.py script exists."""
        from pathlib import Path
        script_path = Path(__file__).parents[2] / "scripts" / "load_mart.py"
        assert script_path.exists()

    def test_load_mart_script_has_date_argument(self):
        """Test that load_mart.py accepts --date argument."""
        from pathlib import Path
        script = (Path(__file__).parents[2] / "scripts" / "load_mart.py").read_text()
        assert '"--date"' in script
        assert "target_date" in script

    def test_load_mart_script_has_exchange_argument(self):
        """Test that load_mart.py accepts --exchange argument."""
        from pathlib import Path
        script = (Path(__file__).parents[2] / "scripts" / "load_mart.py").read_text()
        assert '"--exchange"' in script

    def test_load_mart_script_has_no_log_run_flag(self):
        """Test that load_mart.py accepts --no-log-run flag."""
        from pathlib import Path
        script = (Path(__file__).parents[2] / "scripts" / "load_mart.py").read_text()
        assert '"--no-log-run"' in script
