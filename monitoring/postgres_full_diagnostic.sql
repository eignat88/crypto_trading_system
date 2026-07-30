\set ON_ERROR_STOP on
\pset pager off
\timing on

-- ============================================================================
-- PostgreSQL full read-only diagnostic
-- Target: crypto_trading database; PostgreSQL 17
-- Safe: does not create/alter/drop application objects and does not run VACUUM.
-- Recommended execution: psql -X -f postgres_full_diagnostic.sql
-- ============================================================================

BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15min';
SET LOCAL lock_timeout = '3s';
SET LOCAL idle_in_transaction_session_timeout = '20min';

\echo '00. RUN CONTEXT'
SELECT clock_timestamp() AS collected_at,
       current_database() AS database_name,
       current_user AS database_user,
       inet_server_addr() AS server_address,
       inet_server_port() AS server_port,
       version() AS version,
       pg_postmaster_start_time() AS server_started_at,
       clock_timestamp() - pg_postmaster_start_time() AS server_uptime;

\echo '01. DATABASE SIZE AND CONNECTIONS'
SELECT d.datname,
       pg_size_pretty(pg_database_size(d.datname)) AS database_size,
       d.datallowconn,
       d.datconnlimit,
       age(d.datfrozenxid) AS frozen_xid_age,
       s.numbackends,
       s.xact_commit,
       s.xact_rollback,
       round(100.0 * s.xact_rollback / NULLIF(s.xact_commit + s.xact_rollback, 0), 2)
           AS rollback_percent,
       s.blks_read,
       s.blks_hit,
       round(100.0 * s.blks_hit / NULLIF(s.blks_hit + s.blks_read, 0), 2)
           AS buffer_cache_hit_percent,
       s.temp_files,
       pg_size_pretty(s.temp_bytes) AS temp_written,
       s.deadlocks,
       s.checksum_failures,
       s.stats_reset
FROM pg_database d
LEFT JOIN pg_stat_database s ON s.datid = d.oid
WHERE d.datname = current_database();

\echo '02. IMPORTANT SETTINGS'
SELECT name,
       setting,
       unit,
       source,
       pending_restart,
       CASE name
           WHEN 'shared_buffers' THEN 'Memory used by PostgreSQL buffer cache'
           WHEN 'effective_cache_size' THEN 'Planner estimate of OS + PostgreSQL cache'
           WHEN 'work_mem' THEN 'Per sort/hash operation; do not multiply blindly'
           WHEN 'maintenance_work_mem' THEN 'VACUUM and index build memory'
           WHEN 'max_connections' THEN 'Connection ceiling'
           WHEN 'wal_level' THEN 'WAL detail level'
           WHEN 'max_wal_size' THEN 'Checkpoint/WAL pressure threshold'
           WHEN 'checkpoint_timeout' THEN 'Maximum checkpoint interval'
           WHEN 'autovacuum' THEN 'Automatic vacuum enabled'
           WHEN 'track_io_timing' THEN 'Required for useful I/O timing statistics'
           WHEN 'track_functions' THEN 'Function execution statistics'
           WHEN 'log_min_duration_statement' THEN 'Slow-query logging threshold'
           WHEN 'timezone' THEN 'Database session timezone'
       END AS diagnostic_note
FROM pg_settings
WHERE name IN (
    'shared_buffers','effective_cache_size','work_mem','maintenance_work_mem',
    'max_connections','superuser_reserved_connections',
    'wal_level','max_wal_size','min_wal_size','checkpoint_timeout',
    'checkpoint_completion_target','wal_compression',
    'autovacuum','autovacuum_max_workers','autovacuum_naptime',
    'autovacuum_vacuum_scale_factor','autovacuum_analyze_scale_factor',
    'autovacuum_vacuum_cost_limit','autovacuum_vacuum_cost_delay',
    'track_io_timing','track_functions','track_activity_query_size',
    'log_min_duration_statement','log_checkpoints','log_lock_waits',
    'deadlock_timeout','statement_timeout','idle_in_transaction_session_timeout',
    'timezone','default_transaction_isolation','random_page_cost',
    'effective_io_concurrency','jit','huge_pages'
)
ORDER BY name;

\echo '03. INSTALLED AND AVAILABLE DIAGNOSTIC EXTENSIONS'
SELECT a.name,
       e.extversion AS installed_version,
       a.default_version,
       CASE WHEN e.oid IS NULL THEN false ELSE true END AS installed,
       CASE a.name
           WHEN 'pg_stat_statements' THEN 'Query workload statistics'
           WHEN 'pgstattuple' THEN 'Precise table/index bloat inspection'
           WHEN 'pageinspect' THEN 'Low-level page inspection'
           WHEN 'auto_explain' THEN 'Automatic plans for slow queries'
       END AS purpose
FROM pg_available_extensions a
LEFT JOIN pg_extension e ON e.extname = a.name
WHERE a.name IN ('pg_stat_statements','pgstattuple','pageinspect','auto_explain')
ORDER BY a.name;

\echo '04. SCHEMAS'
SELECT n.nspname AS schema_name,
       pg_get_userbyid(n.nspowner) AS owner,
       count(c.oid) FILTER (WHERE c.relkind IN ('r','p')) AS tables,
       count(c.oid) FILTER (WHERE c.relkind = 'v') AS views,
       count(c.oid) FILTER (WHERE c.relkind = 'm') AS materialized_views,
       pg_size_pretty(COALESCE(sum(pg_total_relation_size(c.oid))
                    FILTER (WHERE c.relkind IN ('r','p','m')), 0)) AS total_size
FROM pg_namespace n
LEFT JOIN pg_class c ON c.relnamespace = n.oid
WHERE n.nspname !~ '^pg_toast'
  AND n.nspname NOT IN ('pg_catalog','information_schema')
GROUP BY n.oid, n.nspname, n.nspowner
ORDER BY COALESCE(sum(pg_total_relation_size(c.oid))
         FILTER (WHERE c.relkind IN ('r','p','m')), 0) DESC;

\echo '05. ALL APPLICATION TABLES: SIZE, ROW ESTIMATE, MAINTENANCE'
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       CASE c.relkind WHEN 'p' THEN 'partitioned table' ELSE 'table' END AS table_type,
       pg_size_pretty(pg_relation_size(c.oid)) AS heap_size,
       pg_size_pretty(pg_indexes_size(c.oid)) AS indexes_size,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       pg_total_relation_size(c.oid) AS total_bytes,
       c.reltuples::bigint AS estimated_rows,
       s.n_live_tup,
       s.n_dead_tup,
       round(100.0 * s.n_dead_tup / NULLIF(s.n_live_tup + s.n_dead_tup, 0), 2)
           AS dead_tuple_percent,
       s.seq_scan,
       s.idx_scan,
       s.n_tup_ins,
       s.n_tup_upd,
       s.n_tup_del,
       s.n_tup_hot_upd,
       s.last_vacuum,
       s.last_autovacuum,
       s.last_analyze,
       s.last_autoanalyze,
       s.vacuum_count,
       s.autovacuum_count,
       s.analyze_count,
       s.autoanalyze_count
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r','p')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
  AND n.nspname !~ '^pg_toast'
ORDER BY pg_total_relation_size(c.oid) DESC, n.nspname, c.relname;

\echo '06. COLUMN DEFINITIONS'
SELECT c.table_schema,
       c.table_name,
       c.ordinal_position,
       c.column_name,
       c.data_type,
       c.udt_name,
       c.numeric_precision,
       c.numeric_scale,
       c.datetime_precision,
       c.is_nullable,
       c.column_default,
       c.is_identity,
       c.identity_generation
FROM information_schema.columns c
WHERE c.table_schema NOT IN ('pg_catalog','information_schema')
ORDER BY c.table_schema, c.table_name, c.ordinal_position;

\echo '07. CONSTRAINTS'
SELECT n.nspname AS schema_name,
       t.relname AS table_name,
       con.conname AS constraint_name,
       CASE con.contype
           WHEN 'p' THEN 'PRIMARY KEY'
           WHEN 'u' THEN 'UNIQUE'
           WHEN 'f' THEN 'FOREIGN KEY'
           WHEN 'c' THEN 'CHECK'
           WHEN 'x' THEN 'EXCLUDE'
           ELSE con.contype::text
       END AS constraint_type,
       con.convalidated AS validated,
       con.condeferrable AS deferrable,
       con.condeferred AS initially_deferred,
       pg_get_constraintdef(con.oid, true) AS definition
FROM pg_constraint con
JOIN pg_class t ON t.oid = con.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY n.nspname, t.relname, constraint_type, con.conname;

\echo '08. TABLES WITHOUT PRIMARY KEY'
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       c.reltuples::bigint AS estimated_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       CASE
           WHEN n.nspname LIKE 'raw\_%' ESCAPE '\' THEN
               'Review: RAW requires a stable source/event key and idempotency'
           ELSE 'Add a PK unless the table is intentionally append-only staging'
       END AS recommendation
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
  AND n.nspname !~ '^pg_toast'
  AND NOT EXISTS (
      SELECT 1
      FROM pg_constraint p
      WHERE p.conrelid = c.oid AND p.contype = 'p'
  )
ORDER BY pg_total_relation_size(c.oid) DESC;

\echo '09. ALL INDEXES AND USAGE'
SELECT ui.schemaname AS schema_name,
       ui.relname AS table_name,
       ui.indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(ui.indexrelid)) AS index_size,
       ui.idx_scan,
       ui.idx_tup_read,
       ui.idx_tup_fetch,
       ix.indisprimary AS is_primary,
       ix.indisunique AS is_unique,
       ix.indisvalid AS is_valid,
       ix.indisready AS is_ready,
       pg_get_indexdef(ui.indexrelid) AS definition
FROM pg_stat_user_indexes ui
JOIN pg_index ix ON ix.indexrelid = ui.indexrelid
ORDER BY pg_relation_size(ui.indexrelid) DESC, ui.schemaname, ui.relname;

\echo '10. POSSIBLY UNUSED INDEXES (EVIDENCE, NOT AUTOMATIC DROP LIST)'
SELECT ui.schemaname AS schema_name,
       ui.relname AS table_name,
       ui.indexrelname AS index_name,
       pg_size_pretty(pg_relation_size(ui.indexrelid)) AS index_size,
       ui.idx_scan,
       st.n_live_tup,
       st.n_tup_ins + st.n_tup_upd + st.n_tup_del AS table_writes,
       (SELECT stats_reset FROM pg_stat_database WHERE datname = current_database())
           AS statistics_since,
       'Do not drop until workload cycle and FK/constraint use are verified' AS warning
FROM pg_stat_user_indexes ui
JOIN pg_index ix ON ix.indexrelid = ui.indexrelid
JOIN pg_stat_user_tables st ON st.relid = ui.relid
WHERE ui.idx_scan = 0
  AND NOT ix.indisprimary
  AND NOT ix.indisunique
  AND pg_relation_size(ui.indexrelid) >= 10 * 1024 * 1024
ORDER BY pg_relation_size(ui.indexrelid) DESC;

\echo '11. EXACT DUPLICATE INDEX DEFINITIONS'
WITH indexes AS (
    SELECT n.nspname,
           t.relname,
           i.indexrelid,
           ci.relname AS index_name,
           i.indrelid,
           i.indkey,
           i.indclass,
           i.indcollation,
           i.indoption,
           i.indexprs,
           i.indpred
    FROM pg_index i
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_class ci ON ci.oid = i.indexrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog','information_schema')
)
SELECT a.nspname AS schema_name,
       a.relname AS table_name,
       a.index_name AS index_1,
       b.index_name AS index_2,
       pg_size_pretty(pg_relation_size(b.indexrelid)) AS removable_size_candidate,
       'Verify constraints and workload before dropping either index' AS warning
FROM indexes a
JOIN indexes b
  ON b.indrelid = a.indrelid
 AND b.indexrelid > a.indexrelid
 AND b.indkey = a.indkey
 AND b.indclass = a.indclass
 AND b.indcollation = a.indcollation
 AND b.indoption = a.indoption
 AND b.indexprs IS NOT DISTINCT FROM a.indexprs
 AND b.indpred IS NOT DISTINCT FROM a.indpred
ORDER BY pg_relation_size(b.indexrelid) DESC;

\echo '12. FOREIGN KEYS WITHOUT A SUPPORTING CHILD-SIDE INDEX'
WITH fk AS (
    SELECT con.oid,
           con.conrelid,
           con.conname,
           con.conkey
    FROM pg_constraint con
    WHERE con.contype = 'f'
),
missing AS (
    SELECT fk.*
    FROM fk
    WHERE NOT EXISTS (
        SELECT 1
        FROM pg_index i
        WHERE i.indrelid = fk.conrelid
          AND i.indisvalid
          AND (i.indkey::smallint[])[0:cardinality(fk.conkey)-1] = fk.conkey
    )
)
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       m.conname AS foreign_key,
       pg_get_constraintdef(m.oid, true) AS definition,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS table_size,
       'Consider child-side index; validate with DELETE/UPDATE and join workload' AS recommendation
FROM missing m
JOIN pg_class c ON c.oid = m.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
ORDER BY pg_total_relation_size(c.oid) DESC;

\echo '13. SEQUENTIAL-SCAN HOTSPOTS'
SELECT schemaname AS schema_name,
       relname AS table_name,
       seq_scan,
       seq_tup_read,
       idx_scan,
       n_live_tup,
       round(seq_tup_read::numeric / NULLIF(seq_scan, 0), 0) AS avg_rows_per_seq_scan,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
       'Review actual frequent queries with EXPLAIN (ANALYZE, BUFFERS); do not add indexes blindly'
           AS recommendation
FROM pg_stat_user_tables
WHERE seq_scan > 0
  AND seq_tup_read > 100000
ORDER BY seq_tup_read DESC
LIMIT 100;

\echo '14. DEAD TUPLES AND VACUUM RISK'
SELECT schemaname AS schema_name,
       relname AS table_name,
       n_live_tup,
       n_dead_tup,
       round(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2)
           AS dead_tuple_percent,
       n_mod_since_analyze,
       last_autovacuum,
       last_autoanalyze,
       autovacuum_count,
       autoanalyze_count,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
       CASE
           WHEN n_dead_tup > 1000000
            AND n_dead_tup > n_live_tup * 0.20 THEN 'HIGH: inspect autovacuum settings'
           WHEN n_dead_tup > 100000 THEN 'MEDIUM: monitor maintenance'
           ELSE 'LOW'
       END AS priority
FROM pg_stat_user_tables
WHERE n_dead_tup > 0 OR n_mod_since_analyze > 0
ORDER BY
    (n_dead_tup > 1000000 AND n_dead_tup > n_live_tup * 0.20) DESC,
    n_dead_tup DESC;

\echo '15. TRANSACTION ID WRAPAROUND RISK'
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       age(c.relfrozenxid) AS xid_age,
       current_setting('autovacuum_freeze_max_age')::bigint AS freeze_max_age,
       round(100.0 * age(c.relfrozenxid)
             / current_setting('autovacuum_freeze_max_age')::bigint, 2)
           AS freeze_limit_percent,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','m')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY age(c.relfrozenxid) DESC
LIMIT 100;

\echo '16. PARTITIONING STATUS AND LARGE NON-PARTITIONED TABLES'
SELECT n.nspname AS schema_name,
       c.relname AS table_name,
       CASE c.relkind WHEN 'p' THEN true ELSE false END AS is_partitioned,
       c.reltuples::bigint AS estimated_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size,
       CASE
           WHEN c.relkind <> 'p'
            AND pg_total_relation_size(c.oid) >= 10::bigint * 1024 * 1024 * 1024
            AND (n.nspname LIKE 'raw\_%' ESCAPE '\' OR n.nspname = 'dds')
           THEN 'Review time-based partitioning only if retention/loading/query patterns benefit'
       END AS recommendation
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY pg_total_relation_size(c.oid) DESC;

\echo '17. PARTITIONS'
SELECT parent_ns.nspname AS parent_schema,
       parent.relname AS parent_table,
       child_ns.nspname AS child_schema,
       child.relname AS child_partition,
       pg_get_expr(child.relpartbound, child.oid, true) AS partition_bound,
       pg_size_pretty(pg_total_relation_size(child.oid)) AS partition_size,
       child.reltuples::bigint AS estimated_rows
FROM pg_inherits inh
JOIN pg_class parent ON parent.oid = inh.inhparent
JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
JOIN pg_class child ON child.oid = inh.inhrelid
JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
ORDER BY parent_ns.nspname, parent.relname, child.relname;

\echo '18. ACTIVE SESSIONS AND LONG TRANSACTIONS'
SELECT pid,
       usename,
       application_name,
       client_addr,
       state,
       backend_type,
       wait_event_type,
       wait_event,
       clock_timestamp() - xact_start AS transaction_age,
       clock_timestamp() - query_start AS query_age,
       clock_timestamp() - state_change AS state_age,
       left(query, 1000) AS query_text
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
ORDER BY xact_start NULLS LAST, query_start NULLS LAST;

\echo '19. BLOCKING CHAINS'
SELECT blocked.pid AS blocked_pid,
       blocked.usename AS blocked_user,
       blocked.application_name AS blocked_application,
       clock_timestamp() - blocked.query_start AS blocked_for,
       blocked.wait_event_type,
       blocked.wait_event,
       blocker.pid AS blocker_pid,
       blocker.usename AS blocker_user,
       blocker.application_name AS blocker_application,
       clock_timestamp() - blocker.query_start AS blocker_query_age,
       left(blocked.query, 500) AS blocked_query,
       left(blocker.query, 500) AS blocker_query
FROM pg_stat_activity blocked
CROSS JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS bp(blocker_pid)
JOIN pg_stat_activity blocker ON blocker.pid = bp.blocker_pid
WHERE blocked.datname = current_database()
ORDER BY blocked.query_start;

\echo '20. CHECKPOINT AND WAL STATISTICS'
SELECT num_timed,
       num_requested,
       round(100.0 * num_requested
             / NULLIF(num_timed + num_requested, 0), 2)
           AS requested_checkpoint_percent,
       restartpoints_timed,
       restartpoints_req,
       restartpoints_done,
       write_time,
       sync_time,
       buffers_written,
       stats_reset
FROM pg_stat_checkpointer;

SELECT buffers_clean,
       maxwritten_clean,
       buffers_alloc,
       stats_reset
FROM pg_stat_bgwriter;

SELECT wal_records,
       wal_fpi,
       pg_size_pretty(wal_bytes::bigint) AS wal_generated,
       wal_buffers_full,
       wal_write,
       wal_sync,
       wal_write_time,
       wal_sync_time,
       stats_reset
FROM pg_stat_wal;

\echo '21. TABLE I/O'
SELECT schemaname AS schema_name,
       relname AS table_name,
       heap_blks_read,
       heap_blks_hit,
       round(100.0 * heap_blks_hit / NULLIF(heap_blks_hit + heap_blks_read, 0), 2)
           AS heap_cache_hit_percent,
       idx_blks_read,
       idx_blks_hit,
       round(100.0 * idx_blks_hit / NULLIF(idx_blks_hit + idx_blks_read, 0), 2)
           AS index_cache_hit_percent,
       toast_blks_read,
       toast_blks_hit
FROM pg_statio_user_tables
ORDER BY heap_blks_read + idx_blks_read DESC
LIMIT 100;

\echo '22. SEQUENCES AND OWNERSHIP'
SELECT schemaname AS schema_name,
       sequencename AS sequence_name,
       data_type,
       start_value,
       min_value,
       max_value,
       increment_by,
       cycle,
       cache_size,
       last_value
FROM pg_sequences
WHERE schemaname NOT IN ('pg_catalog','information_schema')
ORDER BY schemaname, sequencename;

\echo '23. VIEWS AND MATERIALIZED VIEWS'
SELECT schemaname AS schema_name,
       viewname AS object_name,
       'VIEW' AS object_type,
       viewowner AS owner,
       definition
FROM pg_views
WHERE schemaname NOT IN ('pg_catalog','information_schema')
UNION ALL
SELECT schemaname,
       matviewname,
       'MATERIALIZED VIEW',
       matviewowner,
       definition
FROM pg_matviews
WHERE schemaname NOT IN ('pg_catalog','information_schema')
ORDER BY schema_name, object_type, object_name;

\echo '24. TRIGGERS'
SELECT event_object_schema AS schema_name,
       event_object_table AS table_name,
       trigger_name,
       action_timing,
       event_manipulation,
       action_orientation,
       action_statement
FROM information_schema.triggers
WHERE event_object_schema NOT IN ('pg_catalog','information_schema')
ORDER BY event_object_schema, event_object_table, trigger_name, event_manipulation;

\echo '25. PRIVILEGES GRANTED TO PUBLIC'
SELECT table_schema,
       table_name,
       privilege_type,
       grantee,
       grantor,
       is_grantable
FROM information_schema.role_table_grants
WHERE table_schema NOT IN ('pg_catalog','information_schema')
  AND grantee = 'PUBLIC'
ORDER BY table_schema, table_name, privilege_type;

\echo '26. CRYPTO ARCHITECTURE: EXPECTED SCHEMAS'
WITH expected(schema_name, purpose) AS (
    VALUES
        ('raw_account','Private account/exchange payloads'),
        ('raw_market','Public market payloads'),
        ('raw_system','System/integration payloads'),
        ('dds','Normalized operational model'),
        ('mart','Reporting and analytics')
)
SELECT e.schema_name,
       e.purpose,
       (n.oid IS NOT NULL) AS exists,
       CASE WHEN n.oid IS NULL THEN 'Create only when required by approved architecture'
            ELSE 'OK' END AS result
FROM expected e
LEFT JOIN pg_namespace n ON n.nspname = e.schema_name
ORDER BY e.schema_name;

\echo '27. CRYPTO ARCHITECTURE: EXPECTED CORE TABLES'
WITH expected(schema_name, table_name, phase, purpose) AS (
    VALUES
        ('dds','instrument','MVP','Trading instruments'),
        ('dds','candle','MVP','Normalized candles'),
        ('dds','indicator','MVP','Calculated indicators or indicator values'),
        ('dds','market_regime','MVP','Market regime'),
        ('dds','signal','MVP','Strategy signals'),
        ('dds','risk_event','MVP','Risk decisions and events'),
        ('dds','orders','PAPER/LIVE','Orders'),
        ('dds','execution','PAPER/LIVE','Executions/fills'),
        ('dds','position','PAPER/LIVE','Positions'),
        ('dds','balance','PAPER/LIVE','Balances'),
        ('mart','backtest_run','MVP','Reproducible backtest runs'),
        ('mart','trade_performance','MVP','Trade performance'),
        ('mart','equity_curve','MVP','Equity and drawdown')
)
SELECT e.schema_name,
       e.table_name,
       e.phase,
       e.purpose,
       (c.oid IS NOT NULL) AS exists,
       CASE WHEN c.oid IS NULL THEN 'MISSING_OR_DIFFERENT_NAME' ELSE 'OK' END AS result
FROM expected e
LEFT JOIN pg_namespace n ON n.nspname = e.schema_name
LEFT JOIN pg_class c ON c.relnamespace = n.oid
                    AND c.relname = e.table_name
                    AND c.relkind IN ('r','p','v','m')
ORDER BY e.phase, e.schema_name, e.table_name;

\echo '28. DDS.CANDLE STRUCTURAL COMPLIANCE'
WITH expected(column_name, allowed_udt, nullable_expected) AS (
    VALUES
        ('candle_id','int8',false),
        ('instrument_id','int8',false),
        ('interval_code','text',false),
        ('open_time','timestamptz',false),
        ('open_price','numeric',false),
        ('high_price','numeric',false),
        ('low_price','numeric',false),
        ('close_price','numeric',false),
        ('volume','numeric',false),
        ('is_valid','bool',false),
        ('validation_errors','jsonb',true)
),
actual AS (
    SELECT a.attname AS column_name,
           t.typname AS udt_name,
           NOT a.attnotnull AS is_nullable
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE n.nspname = 'dds'
      AND c.relname = 'candle'
      AND a.attnum > 0
      AND NOT a.attisdropped
)
SELECT e.column_name,
       e.allowed_udt AS expected_type,
       a.udt_name AS actual_type,
       e.nullable_expected AS expected_nullable,
       a.is_nullable AS actual_nullable,
       CASE
           WHEN a.column_name IS NULL THEN 'MISSING'
           WHEN a.udt_name <> e.allowed_udt THEN 'WRONG_TYPE'
           WHEN a.is_nullable <> e.nullable_expected THEN 'NULLABILITY_REVIEW'
           ELSE 'OK'
       END AS result
FROM expected e
LEFT JOIN actual a USING (column_name)
ORDER BY e.column_name;

\echo '29. DDS.CANDLE REQUIRED CONSTRAINTS: TEXTUAL COVERAGE'
SELECT con.conname AS constraint_name,
       CASE con.contype
           WHEN 'p' THEN 'PRIMARY KEY'
           WHEN 'u' THEN 'UNIQUE'
           WHEN 'f' THEN 'FOREIGN KEY'
           WHEN 'c' THEN 'CHECK'
       END AS constraint_type,
       con.convalidated AS validated,
       pg_get_constraintdef(con.oid, true) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'dds' AND c.relname = 'candle'
ORDER BY constraint_type, con.conname;

\echo '30. RAW TRACEABILITY COLUMN COVERAGE'
WITH raw_tables AS (
    SELECT n.nspname AS schema_name, c.relname AS table_name, c.oid
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r','p')
      AND n.nspname LIKE 'raw\_%' ESCAPE '\'
),
coverage AS (
    SELECT r.schema_name,
           r.table_name,
           bool_or(a.attname IN ('raw_json','payload','response_json','source_json'))
               AS has_source_payload,
           bool_or(a.attname IN ('request_id','exchange_request_id','correlation_id'))
               AS has_request_id,
           bool_or(a.attname IN ('loaded_at','ingested_at','created_at','received_at'))
               AS has_load_timestamp
    FROM raw_tables r
    LEFT JOIN pg_attribute a
      ON a.attrelid = r.oid AND a.attnum > 0 AND NOT a.attisdropped
    GROUP BY r.schema_name, r.table_name
)
SELECT *,
       CASE
           WHEN has_source_payload AND has_request_id AND has_load_timestamp THEN 'OK'
           ELSE 'REVIEW_RAW_TRACEABILITY'
       END AS result
FROM coverage
ORDER BY schema_name, table_name;

\echo '31. TIMESTAMP TYPE REVIEW'
SELECT table_schema,
       table_name,
       column_name,
       data_type,
       CASE
           WHEN data_type = 'timestamp without time zone'
               THEN 'Prefer timestamptz with UTC semantics'
           WHEN data_type IN ('character varying','text')
            AND column_name ~* '(time|date|timestamp|_at)$'
               THEN 'Possible timestamp stored as text; review'
       END AS recommendation
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog','information_schema')
  AND (
      data_type = 'timestamp without time zone'
      OR (data_type IN ('character varying','text')
          AND column_name ~* '(time|date|timestamp|_at)$')
  )
ORDER BY table_schema, table_name, ordinal_position;

\echo '32. NUMERIC AND MONEY TYPE REVIEW'
SELECT table_schema,
       table_name,
       column_name,
       data_type,
       numeric_precision,
       numeric_scale,
       CASE
           WHEN data_type IN ('real','double precision')
            AND column_name ~* '(price|qty|quantity|amount|balance|fee|volume|capital|pnl)'
               THEN 'HIGH: floating point is unsafe for monetary calculations; review NUMERIC'
           WHEN data_type = 'money'
               THEN 'Review NUMERIC for explicit precision and portability'
           WHEN data_type = 'numeric' AND numeric_scale IS NULL
               THEN 'Unbounded NUMERIC: valid, but review precision policy'
       END AS recommendation
FROM information_schema.columns
WHERE table_schema NOT IN ('pg_catalog','information_schema')
  AND (
      (data_type IN ('real','double precision')
       AND column_name ~* '(price|qty|quantity|amount|balance|fee|volume|capital|pnl)')
      OR data_type = 'money'
      OR (data_type = 'numeric' AND numeric_scale IS NULL)
  )
ORDER BY table_schema, table_name, ordinal_position;

\echo '33. JSONB COLUMNS AND INDEX COVERAGE'
WITH json_columns AS (
    SELECT c.oid AS table_oid,
           n.nspname AS schema_name,
           c.relname AS table_name,
           a.attnum,
           a.attname AS column_name,
           pg_total_relation_size(c.oid) AS total_bytes
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_type t ON t.oid = a.atttypid
    WHERE t.typname = 'jsonb'
      AND a.attnum > 0
      AND NOT a.attisdropped
      AND n.nspname NOT IN ('pg_catalog','information_schema')
)
SELECT j.schema_name,
       j.table_name,
       j.column_name,
       pg_size_pretty(j.total_bytes) AS table_size,
       EXISTS (
           SELECT 1
           FROM pg_index i
           WHERE i.indrelid = j.table_oid
             AND j.attnum = ANY(i.indkey)
       ) AS has_direct_index,
       'Add GIN only for demonstrated JSONB predicates; RAW payload normally remains unindexed'
           AS recommendation
FROM json_columns j
ORDER BY j.total_bytes DESC;

\echo '34. OBJECT COMMENTS / DOCUMENTATION COVERAGE'
SELECT n.nspname AS schema_name,
       c.relname AS object_name,
       CASE c.relkind
           WHEN 'r' THEN 'TABLE'
           WHEN 'p' THEN 'PARTITIONED TABLE'
           WHEN 'v' THEN 'VIEW'
           WHEN 'm' THEN 'MATERIALIZED VIEW'
       END AS object_type,
       obj_description(c.oid, 'pg_class') AS comment,
       CASE WHEN obj_description(c.oid, 'pg_class') IS NULL
            THEN 'COMMENT MISSING' ELSE 'OK' END AS result
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','p','v','m')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
ORDER BY n.nspname, c.relname;

\echo '35. RECOMMENDATION SUMMARY'
WITH facts AS (
    SELECT
        (SELECT count(*)
         FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
         WHERE c.relkind IN ('r','p')
           AND n.nspname NOT IN ('pg_catalog','information_schema')
           AND NOT EXISTS (
               SELECT 1 FROM pg_constraint p
               WHERE p.conrelid=c.oid AND p.contype='p')) AS no_pk,
        (SELECT count(*) FROM pg_stat_user_tables
         WHERE n_dead_tup > 1000000
           AND n_dead_tup > n_live_tup * 0.20) AS vacuum_risk,
        (SELECT count(*) FROM information_schema.columns
         WHERE table_schema NOT IN ('pg_catalog','information_schema')
           AND data_type = 'timestamp without time zone') AS timestamp_without_tz,
        (SELECT count(*) FROM information_schema.columns
         WHERE table_schema NOT IN ('pg_catalog','information_schema')
           AND data_type IN ('real','double precision')
           AND column_name ~* '(price|qty|quantity|amount|balance|fee|volume|capital|pnl)')
           AS monetary_float,
        (SELECT count(*) FROM pg_stat_activity
         WHERE datname=current_database()
           AND pid<>pg_backend_pid()
           AND xact_start < clock_timestamp() - interval '10 minutes') AS long_transactions
)
SELECT priority, category, issue_count, recommendation
FROM (
    SELECT 10 AS sort_order, 'P1' AS priority, 'Monetary types' AS category,
           monetary_float AS issue_count,
           'Replace monetary floating-point columns only through a reviewed migration'
               AS recommendation
    FROM facts
    UNION ALL
    SELECT 20, 'P1', 'Long transactions', long_transactions,
           'Find the owner and safely finish/rollback; do not terminate blindly'
    FROM facts
    UNION ALL
    SELECT 30, 'P1', 'VACUUM risk', vacuum_risk,
           'Inspect per-table autovacuum and write pattern; avoid VACUUM FULL during operation'
    FROM facts
    UNION ALL
    SELECT 40, 'P2', 'Missing primary keys', no_pk,
           'Define stable keys and idempotency; large-table key builds require a separate plan'
    FROM facts
    UNION ALL
    SELECT 50, 'P2', 'Timestamp without time zone', timestamp_without_tz,
           'Standardize event time on timestamptz/UTC through a controlled migration'
    FROM facts
) r
WHERE issue_count > 0
ORDER BY sort_order;

COMMIT;

\echo 'DIAGNOSTIC COMPLETED SUCCESSFULLY'
