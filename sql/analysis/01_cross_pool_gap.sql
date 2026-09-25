-- ANALYSIS: the price gap between two pools of the same pair, at every swap of either pool.
--
--   {lo:String}  the pool with the lower fee    {hi:String}  the pool with the higher fee
--
-- Both pools must hold the same two tokens in the same order (token0/token1), so the ratio of
-- their prices is the square of the ratio of their sqrtPriceX96 and the decimals cancel.
-- sqrtPriceX96 in a Swap log is the price AFTER that swap. For each swap of one pool, the
-- price in effect in the other pool is the one left by its last swap strictly before it in
-- chain order: ASOF JOIN on (block_number, log_index), encoded as one sortable integer.
-- The gap is signed as lo relative to hi and measured as a log ratio in basis points:
-- 10,000 * ln(P_lo / P_hi) = 20,000 * ln(sqrtP_lo / sqrtP_hi). For gaps of a few bps it
-- equals the relative difference to within a hundredth of a bp; unlike the relative
-- difference it treats a price that doubles and one that halves alike, instead of
-- stopping at -10,000 bps when one pool's price collapses in a thin tick range.
--
-- Chain position is block_number * 2^32 + log_index in one UInt64, which keeps the order of
-- (block_number, log_index) for any log_index below 2^32.
-- ASOF JOIN needs an equality column; both sides carry the same constant, so the join is on
-- position alone. A swap that comes before the other pool's first swap has nothing to join
-- to and is dropped (ASOF is an inner join here).

WITH
    lo AS
    (
        SELECT bitShiftLeft(block_number, 32) + log_index AS pos, toUInt8(1) AS pair,
               toFloat64(sqrt_price_x96) AS sp
        FROM raw_swaps
        WHERE pool_address = {lo:String}
    ),
    hi AS
    (
        SELECT bitShiftLeft(block_number, 32) + log_index AS pos, toUInt8(1) AS pair,
               toFloat64(sqrt_price_x96) AS sp
        FROM raw_swaps
        WHERE pool_address = {hi:String}
    ),
    gaps AS
    (
        SELECT 'lo' AS moved, 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM lo ASOF JOIN hi ON lo.pair = hi.pair AND lo.pos > hi.pos
        UNION ALL
        SELECT 'hi' AS moved, 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM hi ASOF JOIN lo ON hi.pair = lo.pair AND hi.pos > lo.pos
    )
SELECT
    moved,
    count()                                                  AS swaps,
    quantileExact(0.50)(abs(gap_bps))                        AS abs_gap_p50_bps,
    quantileExact(0.95)(abs(gap_bps))                        AS abs_gap_p95_bps,
    quantileExact(0.99)(abs(gap_bps))                        AS abs_gap_p99_bps,
    max(abs(gap_bps))                                        AS abs_gap_max_bps,
    avg(gap_bps)                                             AS mean_signed_gap_bps,
    countIf(abs(gap_bps) > {fee_bps:Float64})                AS beyond_combined_fee
FROM gaps
GROUP BY moved WITH ROLLUP
ORDER BY moved = '' , moved
