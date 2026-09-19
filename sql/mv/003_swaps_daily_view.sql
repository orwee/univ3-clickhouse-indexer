-- What everyone should read. The GROUP BY + sum() is NOT decoration:
--   * every insert into raw_swaps adds NEW rows to swaps_daily_agg, one per (pool, day)
--     present in that insert block; the same (pool, day) is there several times until
--     a background merge collapses it, and merges are eventual and never guaranteed;
--   * a day that straddles the backfill cut-off has one row from the backfill and
--     others from the trigger.
-- Summing at read time gives the right answer in every one of those states.
-- (SELECT ... FINAL on the target would too, but it costs a merge at read time.)

CREATE VIEW IF NOT EXISTS swaps_daily AS
SELECT
    pool_address,
    block_date,
    sum(swaps)            AS swaps,
    sum(amount0_abs_sum)  AS amount0_abs_sum,
    sum(amount1_abs_sum)  AS amount1_abs_sum
FROM swaps_daily_agg
GROUP BY pool_address, block_date
