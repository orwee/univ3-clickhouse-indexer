-- Target table of the materialized view: daily aggregates per pool, in RAW units.
--
-- AggregatingMergeTree collapses rows with the same sorting key by applying the
-- aggregate function of each column, but only WHEN PARTS MERGE, which is eventual.
-- Until then one (pool, day) can be spread over several rows: one per insert block
-- that touched it. Reading therefore always goes through the view `swaps_daily`.
--
-- SimpleAggregateFunction(sum, T) stores a plain T and sums it on merge. It is the
-- cheap form, valid for functions whose state IS their result (sum, min, max, any).
-- AggregateFunction(...) with -State / -Merge is only needed for avg, uniq, quantile.
--
-- Widths, so that nothing overflows:
--   swaps            UInt64  a counter. 863,587 swaps in 31 days; 2^64 is 1.8e19.
--   amount*_abs_sum  UInt256 one |amount| is at most 2^255 (it comes from an int256).
--                    The largest real one is 1,136 WETH = 2^70, the busiest pool-day
--                    has ~30,000 swaps = 2^15, so a real daily sum is about 2^85 and
--                    UInt256 leaves ~2^170 of headroom. UInt128 would hold the real
--                    data too; UInt256 is what needs no argument, because a sum of
--                    token amounts is bounded by supply x turnover, not by 2^128.
--                    abs(Int256) is already UInt256 in ClickHouse, and so is its sum.

CREATE TABLE IF NOT EXISTS swaps_daily_agg
(
    pool_address     LowCardinality(String),
    block_date       Date,
    swaps            SimpleAggregateFunction(sum, UInt64),
    amount0_abs_sum  SimpleAggregateFunction(sum, UInt256),
    amount1_abs_sum  SimpleAggregateFunction(sum, UInt256)
)
ENGINE = AggregatingMergeTree
ORDER BY (pool_address, block_date)
