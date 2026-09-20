-- Recomputation of the daily aggregates, straight from raw_swaps. No dbt model and no
-- materialized view is read here. What agreeing with the view proves is the BOOKKEEPING of
-- the insert trigger (nothing lost, nothing counted twice, across backfill, incremental
-- loads, full reloads and repairs). It proves nothing about the data: same table, same rows.
-- The arithmetic is written differently on purpose, so that a shared mistake in an
-- expression would not hide:
--   * the day comes from toStartOfDay(..., 'UTC'), not from toDate();
--   * |amount| is "what came in minus what went out" (sumIf positives - sumIf negatives),
--     not abs(). For a signed integer these are the same number by definition.
-- Raw units throughout: Int256 sums, no scaling, no float.

SELECT
    pool_address,
    toDate(toStartOfDay(block_timestamp, 'UTC'))                                  AS block_date,
    count()                                                                       AS swaps,
    toUInt256(sumIf(amount0, amount0 > 0) - sumIf(amount0, amount0 < 0))          AS amount0_abs_sum,
    toUInt256(sumIf(amount1, amount1 > 0) - sumIf(amount1, amount1 < 0))          AS amount1_abs_sum
FROM raw_swaps
GROUP BY pool_address, block_date
ORDER BY pool_address, block_date
