-- ANALYSIS: the gap between the two pools at the END of each block, when every transaction of
-- the block has run. A gap inside a block can be the first leg of an arbitrage that the same
-- transaction closes; nobody outside could trade it. The last swap of a block, of either
-- pool, leaves the prices a new block starts from.
--
--   {lo:String} {hi:String} {fee_bps:Float64}  as in 03_cross_pool_episodes.sql

WITH
    lo AS
    (
        SELECT block_number AS blk, bitShiftLeft(block_number, 32) + log_index AS pos,
               toUInt8(1) AS pair, toFloat64(sqrt_price_x96) AS sp
        FROM raw_swaps
        WHERE pool_address = {lo:String}
    ),
    hi AS
    (
        SELECT block_number AS blk, bitShiftLeft(block_number, 32) + log_index AS pos,
               toUInt8(1) AS pair, toFloat64(sqrt_price_x96) AS sp
        FROM raw_swaps
        WHERE pool_address = {hi:String}
    ),
    events AS
    (
        SELECT lo.blk AS blk, lo.pos AS pos, 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM lo ASOF JOIN hi ON lo.pair = hi.pair AND lo.pos > hi.pos
        UNION ALL
        SELECT hi.blk AS blk, hi.pos AS pos, 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM hi ASOF JOIN lo ON hi.pair = lo.pair AND hi.pos > lo.pos
    ),
    block_ends AS
    (
        SELECT blk, argMax(gap_bps, pos) AS end_gap_bps
        FROM events
        GROUP BY blk
    )
SELECT
    count()                                                     AS blocks,
    countIf(abs(end_gap_bps) <= {fee_bps:Float64})              AS blocks_ending_within_the_fee,
    blocks_ending_within_the_fee / blocks                       AS share_within_the_fee,
    quantileExact(0.50)(abs(end_gap_bps))                       AS end_gap_p50_bps,
    quantileExact(0.99)(abs(end_gap_bps))                       AS end_gap_p99_bps
FROM block_ends
