-- One-off backfill of what was in raw_swaps BEFORE the materialized view existed.
-- Same SELECT as the view, plus a cut-off: rows up to {cutoff_block:UInt64}, inclusive.
-- Rows above the cut-off are the trigger's business. Get the cut-off wrong in either
-- direction and rows are missed or counted twice.
--
-- NOT idempotent: run it twice and the history is counted twice (there is a test that
-- shows it). To redo it: TRUNCATE swaps_daily_agg first, with ingestion stopped.

INSERT INTO swaps_daily_agg
SELECT
    pool_address,
    toDate(block_timestamp, 'UTC') AS block_date,
    count()                        AS swaps,
    sum(abs(amount0))              AS amount0_abs_sum,
    sum(abs(amount1))              AS amount1_abs_sum
FROM raw_swaps
WHERE block_number <= {cutoff_block:UInt64}
GROUP BY pool_address, block_date
