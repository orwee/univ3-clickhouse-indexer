-- title: Rows per pool and day
-- question: How many swaps does each pool have on each UTC day?
-- problem: a day whose count collapses against its neighbours for a busy pool (a hole in
--          the backfill), or a first/last day that is not partial when it should be.
-- expect: informational
SELECT
    pool_address,
    toDate(block_timestamp) AS day,
    count() AS swaps,
    min(block_number) AS first_block,
    max(block_number) AS last_block
FROM raw_swaps
GROUP BY pool_address, day
ORDER BY pool_address, day
