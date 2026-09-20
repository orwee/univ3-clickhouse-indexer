-- swaps_daily (through the materialized view) against a direct GROUP BY over raw_swaps.
-- Returns the (pool, day) pairs that differ or exist on one side only. Expected: no rows.

SELECT
    coalesce(nullIf(mv.pool_address, ''), direct.pool_address)   AS pool_address,
    if(mv.pool_address = '', direct.block_date, mv.block_date)   AS block_date,
    mv.swaps AS mv_swaps,                     direct.swaps AS direct_swaps,
    mv.amount0_abs_sum AS mv_amount0,         direct.amount0_abs_sum AS direct_amount0,
    mv.amount1_abs_sum AS mv_amount1,         direct.amount1_abs_sum AS direct_amount1
FROM swaps_daily AS mv
FULL OUTER JOIN
(
    SELECT
        pool_address,
        toDate(block_timestamp, 'UTC') AS block_date,
        count()                        AS swaps,
        sum(abs(amount0))              AS amount0_abs_sum,
        sum(abs(amount1))              AS amount1_abs_sum
    FROM raw_swaps
    GROUP BY pool_address, block_date
) AS direct USING (pool_address, block_date)
WHERE mv.swaps != direct.swaps
   OR mv.amount0_abs_sum != direct.amount0_abs_sum
   OR mv.amount1_abs_sum != direct.amount1_abs_sum
ORDER BY pool_address, block_date
