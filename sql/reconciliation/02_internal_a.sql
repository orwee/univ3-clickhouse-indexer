-- RECONCILIATION A, internal: the recomputation above against swaps_daily (the read view
-- over the materialized view), in RAW units. Both come from the same rows, so the
-- expected difference is EXACTLY zero. Any row returned here is a defect in the pipeline:
-- a backfill run twice, a reload the view did not survive, a cut-off off by one.

WITH recomputed AS
(
    SELECT
        pool_address,
        toDate(toStartOfDay(block_timestamp, 'UTC'))                             AS block_date,
        count()                                                                  AS swaps,
        toUInt256(sumIf(amount0, amount0 > 0) - sumIf(amount0, amount0 < 0))     AS amount0_abs_sum,
        toUInt256(sumIf(amount1, amount1 > 0) - sumIf(amount1, amount1 < 0))     AS amount1_abs_sum
    FROM raw_swaps
    GROUP BY pool_address, block_date
)
SELECT
    if(r.pool_address != '', r.pool_address, v.pool_address)   AS pool_address,
    if(r.pool_address != '', r.block_date, v.block_date)       AS block_date,
    multiIf(r.pool_address = '', 'only in swaps_daily',
            v.pool_address = '', 'only in recomputation', 'differs')  AS problem,
    r.swaps              AS recomputed_swaps,     v.swaps              AS view_swaps,
    r.amount0_abs_sum    AS recomputed_amount0,   v.amount0_abs_sum    AS view_amount0,
    r.amount1_abs_sum    AS recomputed_amount1,   v.amount1_abs_sum    AS view_amount1
FROM recomputed AS r
FULL OUTER JOIN swaps_daily AS v
    ON v.pool_address = r.pool_address AND v.block_date = r.block_date
WHERE r.pool_address = '' OR v.pool_address = ''
   OR r.swaps != v.swaps
   OR r.amount0_abs_sum != v.amount0_abs_sum
   OR r.amount1_abs_sum != v.amount1_abs_sum
ORDER BY pool_address, block_date
-- join_use_nulls is PINNED to 0. These comparisons rely on an unmatched side being filled
-- with defaults ('' and 0). With join_use_nulls = 1 (a user profile can set it) they would
-- compare with NULL, the WHERE would drop exactly the rows that matter, and a day missing
-- from one side would read as "no differences".
SETTINGS join_use_nulls = 0
