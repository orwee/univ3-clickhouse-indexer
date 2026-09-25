-- ANALYSIS: how the absolute price gap between the two pools is distributed, in 1-bp buckets
-- up to 20 bps and one open bucket above. Same gap as 01_cross_pool_gap.sql, same parameters.

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
        SELECT 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM lo ASOF JOIN hi ON lo.pair = hi.pair AND lo.pos > hi.pos
        UNION ALL
        SELECT 2e4 * log(lo.sp / hi.sp) AS gap_bps
        FROM hi ASOF JOIN lo ON hi.pair = lo.pair AND hi.pos > lo.pos
    )
SELECT
    least(toUInt32(floor(abs(gap_bps))), 20) AS bucket_bps,
    count()                                  AS swaps
FROM gaps
GROUP BY bucket_bps
ORDER BY bucket_bps
