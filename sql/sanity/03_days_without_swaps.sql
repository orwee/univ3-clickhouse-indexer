-- title: Days without swaps, per pool
-- question: Between the first and the last day of data, which days have no swap at all
--           for each pool?
-- problem: any row for a busy pool, or the SAME day missing for every pool (then it is
--          the backfill, not the market). A quiet pool (wstETH/USDC 0.3%) can legitimately
--          skip days: read this next to query 01.
-- expect: informational
WITH
    (SELECT toDate(min(block_timestamp)) FROM raw_swaps) AS first_day,
    (SELECT toDate(max(block_timestamp)) FROM raw_swaps) AS last_day
SELECT
    pool_address,
    day
FROM
(
    SELECT
        pool_address,
        arrayJoin(arrayMap(i -> first_day + i, range(toUInt32(last_day - first_day) + 1))) AS day
    FROM (SELECT DISTINCT pool_address FROM raw_swaps)
) AS calendar
LEFT ANTI JOIN
(
    SELECT DISTINCT pool_address, toDate(block_timestamp) AS day FROM raw_swaps
) AS seen USING (pool_address, day)
ORDER BY pool_address, day
