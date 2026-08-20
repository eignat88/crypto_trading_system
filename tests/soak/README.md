# Paper soak test

Run the paper application for 24–72 hours with `TRADING_MODE=paper` and
`TRADING_SYMBOLS=BTCUSDT,ETHUSDT`. During the run, query
`monitoring.runtime_health` and verify that the heartbeat remains fresh and the
sequence is monotonic. Restart once during the test and verify that the sequence
continues and no `client_order_id` is duplicated.

The soak is deliberately not part of the normal pytest suite. Stop immediately
on a stale/absent heartbeat, failed reconciliation, database outage, duplicate
order, or breached risk limit, retaining the database and logs for diagnosis.
