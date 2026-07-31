/*
Read-only readiness diagnostics for one RAW -> DDS candle stream.

SQLAlchemy bind parameters:
  :exchange_name, :symbol, :interval_code

The query returns one row. It does not create, update, or delete data.
*/
WITH params AS (
    SELECT
        CAST(:exchange_name AS text) AS exchange_name,
        CAST(:symbol AS text) AS symbol,
        CAST(:interval_code AS text) AS interval_code,
        CASE CAST(:interval_code AS text)
            WHEN '1m'  THEN interval '1 minute'
            WHEN '3m'  THEN interval '3 minutes'
            WHEN '5m'  THEN interval '5 minutes'
            WHEN '15m' THEN interval '15 minutes'
            WHEN '30m' THEN interval '30 minutes'
            WHEN '1h'  THEN interval '1 hour'
            WHEN '2h'  THEN interval '2 hours'
            WHEN '4h'  THEN interval '4 hours'
            WHEN '6h'  THEN interval '6 hours'
            WHEN '12h' THEN interval '12 hours'
            WHEN '1d'  THEN interval '1 day'
            ELSE NULL
        END AS expected_step
),
raw_rows AS (
    SELECT r.*
    FROM raw_market.candles r
    CROSS JOIN params p
    WHERE r.exchange_name = p.exchange_name
      AND r.symbol = p.symbol
      AND r.interval_code = p.interval_code
),
raw_ordered AS (
    SELECT
        r.open_time,
        lag(r.open_time) OVER (ORDER BY r.open_time) AS previous_open_time
    FROM raw_rows r
),
raw_stats AS (
    SELECT
        count(*)::bigint AS raw_count,
        min(open_time) AS raw_min_open_time,
        max(open_time) AS raw_max_open_time,
        count(*) FILTER (
            WHERE close_time IS NULL OR close_time <= open_time
        )::bigint AS invalid_time_count,
        count(*) FILTER (
            WHERE open_price <= 0 OR high_price <= 0
               OR low_price <= 0 OR close_price <= 0
        )::bigint AS non_positive_price_count,
        count(*) FILTER (
            WHERE high_price < open_price OR high_price < close_price
               OR low_price > open_price OR low_price > close_price
               OR high_price < low_price
        )::bigint AS invalid_ohlc_count,
        count(*) FILTER (
            WHERE COALESCE(volume, 0) < 0
               OR quote_volume < 0 OR trade_count < 0
        )::bigint AS negative_activity_count
    FROM raw_rows
),
duplicate_stats AS (
    SELECT count(*)::bigint AS duplicate_key_groups
    FROM (
        SELECT exchange_name, symbol, interval_code, open_time
        FROM raw_rows
        GROUP BY exchange_name, symbol, interval_code, open_time
        HAVING count(*) > 1
    ) d
),
gap_stats AS (
    SELECT count(*)::bigint AS gap_count
    FROM raw_ordered o
    CROSS JOIN params p
    WHERE p.expected_step IS NOT NULL
      AND o.previous_open_time IS NOT NULL
      AND o.open_time - o.previous_open_time > p.expected_step
),
latest_loading AS (
    SELECT j.*
    FROM raw_system.loading_journal j
    CROSS JOIN params p
    WHERE j.exchange_name = p.exchange_name
      AND j.symbol = p.symbol
      AND j.interval_code = p.interval_code
    ORDER BY j.started_at DESC, j.id DESC
    LIMIT 1
),
etl_ranked AS (
    SELECT
        r.*,
        row_number() OVER (ORDER BY r.started_at DESC, r.run_id DESC) AS rn
    FROM dds.etl_run r
    CROSS JOIN params p
    WHERE r.exchange_name = p.exchange_name
      AND r.symbol = p.symbol
      AND r.interval_code = p.interval_code
),
etl_latest AS (
    SELECT * FROM etl_ranked WHERE rn = 1
),
etl_previous AS (
    SELECT * FROM etl_ranked WHERE rn = 2
),
checkpoint AS (
    SELECT c.*
    FROM dds.etl_checkpoint c
    CROSS JOIN params p
    WHERE c.exchange_name = p.exchange_name
      AND c.symbol = p.symbol
      AND c.interval_code = p.interval_code
),
dds_stats AS (
    SELECT
        count(*)::bigint AS dds_count,
        min(c.open_time) AS dds_min_open_time,
        max(c.open_time) AS dds_max_open_time
    FROM dds.candle c
    JOIN dds.instrument i ON i.instrument_id = c.instrument_id
    CROSS JOIN params p
    WHERE i.exchange_name = p.exchange_name
      AND i.symbol = p.symbol
      AND c.interval_code = p.interval_code
),
dq_stats AS (
    SELECT
        count(*)::bigint AS data_quality_event_count,
        max(q.last_seen_at) AS latest_data_quality_event_at
    FROM dds.data_quality_event q
    CROSS JOIN params p
    WHERE q.exchange_name = p.exchange_name
      AND q.symbol = p.symbol
      AND q.interval_code = p.interval_code
),
running_stats AS (
    SELECT count(*)::bigint AS running_etl_count
    FROM dds.etl_run r
    CROSS JOIN params p
    WHERE r.exchange_name = p.exchange_name
      AND r.symbol = p.symbol
      AND r.interval_code = p.interval_code
      AND r.status = 'running'
)
SELECT
    current_database() AS database_name,
    current_setting('server_version') AS postgres_version,
    clock_timestamp() AS checked_at,
    p.exchange_name,
    p.symbol,
    p.interval_code,
    (p.expected_step IS NOT NULL) AS interval_supported,
    rs.raw_count,
    rs.raw_min_open_time,
    rs.raw_max_open_time,
    ds.duplicate_key_groups,
    gs.gap_count,
    rs.invalid_time_count,
    rs.non_positive_price_count,
    rs.invalid_ohlc_count,
    rs.negative_activity_count,
    ll.id AS loading_journal_id,
    ll.status AS loading_journal_status,
    ll.rows_loaded AS loading_journal_rows_loaded,
    ll.started_at AS loading_journal_started_at,
    ll.completed_at AS loading_journal_completed_at,
    ll.error_message AS loading_journal_error,
    ep.run_id AS previous_etl_run_id,
    ep.status AS previous_etl_status,
    ep.source_count AS previous_source_count,
    ep.inserted_count AS previous_inserted_count,
    ep.rejected_count AS previous_rejected_count,
    ep.deferred_count AS previous_deferred_count,
    el.run_id AS latest_etl_run_id,
    el.status AS latest_etl_status,
    el.source_count AS latest_source_count,
    el.inserted_count AS latest_inserted_count,
    el.rejected_count AS latest_rejected_count,
    el.deferred_count AS latest_deferred_count,
    el.error_message AS latest_etl_error,
    cp.last_loaded_at AS checkpoint_last_loaded_at,
    cp.last_run_at AS checkpoint_last_run_at,
    dd.dds_count,
    dd.dds_min_open_time,
    dd.dds_max_open_time,
    dq.data_quality_event_count,
    dq.latest_data_quality_event_at,
    run.running_etl_count,
    (
        rs.raw_count > 0
        AND ds.duplicate_key_groups = 0
        AND gs.gap_count = 0
        AND rs.invalid_time_count = 0
        AND rs.non_positive_price_count = 0
        AND rs.invalid_ohlc_count = 0
        AND rs.negative_activity_count = 0
        AND ll.status = 'success'
        AND ll.completed_at IS NOT NULL
    ) AS raw_check_success,
    (
        ep.status = 'success'
        AND el.status = 'success'
        AND el.inserted_count = 0
        AND el.rejected_count = 0
        AND el.deferred_count = 0
    ) AS raw_to_dds_repeat_explainable,
    (
        cp.exchange_name IS NOT NULL
        AND el.status = 'success'
        AND run.running_etl_count = 0
        AND dq.data_quality_event_count = 0
        AND dd.dds_count > 0
    ) AS database_final_check_success
FROM params p
CROSS JOIN raw_stats rs
CROSS JOIN duplicate_stats ds
CROSS JOIN gap_stats gs
CROSS JOIN dds_stats dd
CROSS JOIN dq_stats dq
CROSS JOIN running_stats run
LEFT JOIN latest_loading ll ON true
LEFT JOIN etl_previous ep ON true
LEFT JOIN etl_latest el ON true
LEFT JOIN checkpoint cp ON true;
