
ALTER TABLE dds.indicator
    ADD COLUMN IF NOT EXISTS model_version text;

UPDATE dds.indicator
SET model_version = 'legacy_unversioned'
WHERE model_version IS NULL;

ALTER TABLE dds.indicator
    ALTER COLUMN model_version SET NOT NULL;

ALTER TABLE dds.indicator
    ALTER COLUMN model_version SET DEFAULT 'legacy_unversioned';

ALTER TABLE dds.indicator
    DROP CONSTRAINT IF EXISTS uq_dds_indicator;

ALTER TABLE dds.indicator
    ADD CONSTRAINT uq_dds_indicator
    UNIQUE (candle_id, indicator_name, indicator_params, model_version);

CREATE INDEX IF NOT EXISTS idx_dds_indicator_model
    ON dds.indicator (model_version, indicator_name, candle_id);

ALTER TABLE dds.market_regime
    ADD COLUMN IF NOT EXISTS indicator_model_version text;

ALTER TABLE dds.market_regime
    ADD COLUMN IF NOT EXISTS regime_model_version text;

UPDATE dds.market_regime
SET
    indicator_model_version = COALESCE(indicator_model_version, 'legacy_unversioned'),
    regime_model_version = COALESCE(regime_model_version, 'legacy_unversioned')
WHERE indicator_model_version IS NULL
   OR regime_model_version IS NULL;

ALTER TABLE dds.market_regime
    ALTER COLUMN indicator_model_version SET NOT NULL;

ALTER TABLE dds.market_regime
    ALTER COLUMN regime_model_version SET NOT NULL;

ALTER TABLE dds.market_regime
    ALTER COLUMN indicator_model_version SET DEFAULT 'legacy_unversioned';

ALTER TABLE dds.market_regime
    ALTER COLUMN regime_model_version SET DEFAULT 'legacy_unversioned';

ALTER TABLE dds.market_regime
    DROP CONSTRAINT IF EXISTS uq_dds_market_regime;

ALTER TABLE dds.market_regime
    ADD CONSTRAINT uq_dds_market_regime
    UNIQUE (candle_id, regime_model_version);

CREATE INDEX IF NOT EXISTS idx_dds_market_regime_model
    ON dds.market_regime (regime_model_version, candle_id);

ALTER TABLE mart.backtest_run
    ADD COLUMN IF NOT EXISTS dataset_fingerprint text;

ALTER TABLE mart.backtest_run
    ADD COLUMN IF NOT EXISTS indicator_model_version text;

ALTER TABLE mart.backtest_run
    ADD COLUMN IF NOT EXISTS regime_model_version text;

ALTER TABLE mart.backtest_run
    ADD COLUMN IF NOT EXISTS execution_model_version text;

UPDATE mart.backtest_run
SET
    indicator_model_version = COALESCE(indicator_model_version, 'legacy_unversioned'),
    regime_model_version = COALESCE(regime_model_version, 'legacy_unversioned'),
    execution_model_version = COALESCE(execution_model_version, 'legacy_unversioned')
WHERE indicator_model_version IS NULL
   OR regime_model_version IS NULL
   OR execution_model_version IS NULL;

CREATE INDEX IF NOT EXISTS idx_backtest_run_dataset_fingerprint
    ON mart.backtest_run (dataset_fingerprint);

CREATE INDEX IF NOT EXISTS idx_backtest_run_model_versions
    ON mart.backtest_run (
        indicator_model_version,
        regime_model_version,
        execution_model_version
    );
