-- The materialized view. In ClickHouse this is an INSERT TRIGGER, not a stored query:
-- it runs its SELECT over each block of rows being inserted into raw_swaps and writes
-- the result into swaps_daily_agg. It never reads raw_swaps itself, so rows that were
-- already in the table when the view was created are NOT in the target. They have to
-- be backfilled once, by hand (010_backfill.sql).
--
-- `TO swaps_daily_agg` is explicit on purpose. Without TO, ClickHouse creates a hidden
-- `.inner` table that cannot be given its own engine settings, is awkward to backfill
-- and disappears with the view. With TO the target is an ordinary table that outlives
-- the view and can be truncated, backfilled and inspected.
--
-- The column names and types of the SELECT must match the target: count() is UInt64,
-- sum(abs(Int256)) is UInt256. The day is the UTC day, stated explicitly.

CREATE MATERIALIZED VIEW IF NOT EXISTS swaps_daily_mv TO swaps_daily_agg AS
SELECT
    pool_address,
    toDate(block_timestamp, 'UTC') AS block_date,
    count()                        AS swaps,
    sum(abs(amount0))              AS amount0_abs_sum,
    sum(abs(amount1))              AS amount1_abs_sum
FROM raw_swaps
GROUP BY pool_address, block_date
