-- EVIDENCE: is there ONE swap about the size of a pool-day's difference?
--
--   {pool:String} {day:Date}        the pool-day
--   {target_usd:Float64}            the absolute difference of that pool-day, in USD
--   {tolerance:Float64}             0.05 = swaps within 5% of the target
--   {minutes:UInt32}                how far past each midnight to look, on both sides
--   stable_*                        as in 03_external_b.sql
--
-- Looks at the UTC day plus `minutes` before its first midnight and after its last one, so a
-- swap that a different day boundary would move in or out of the day is seen too.
-- `where_in_day` says where a swap sits: '' for the body of the day.
-- The day's median tick and liquidity come along, to compare each swap with. No judgement here.

WITH
    toDateTime({day:Date}, 'UTC')                        AS day_start,
    day_start + INTERVAL 1 DAY                           AS day_end,
    toIntervalMinute({minutes:UInt32})                   AS margin,
    priced AS
    (
        SELECT
            block_timestamp, block_number, log_index, tick, liquidity,
            toFloat64(if(arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1,
                         abs(amount0), abs(amount1)))
                / pow(10, arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)))
                AS usd
        FROM raw_swaps
        WHERE pool_address = {pool:String}
          AND block_timestamp >= day_start - margin
          AND block_timestamp <  day_end + margin
    ),
    of_the_day AS
    (
        SELECT
            count()                                  AS day_swaps,
            sum(usd)                                 AS day_usd,
            quantileExact(0.5)(tick)                 AS day_median_tick,
            toFloat64(quantileExact(0.5)(liquidity)) AS day_median_liquidity
        FROM priced
        WHERE block_timestamp >= day_start AND block_timestamp < day_end
    )
SELECT
    toString(s.block_timestamp)                                            AS swap_time,
    s.usd                                                                  AS swap_usd,
    s.usd / {target_usd:Float64} - 1                                       AS swap_over_target_minus_1,
    multiIf(s.block_timestamp <  day_start,          'previous day, last minutes',
            s.block_timestamp >= day_end,            'next day, first minutes',
            s.block_timestamp <  day_start + margin, 'first minutes of the day',
            s.block_timestamp >= day_end - margin,   'last minutes of the day',
            '')                                                            AS where_in_day,
    s.tick                                                                 AS swap_tick,
    toFloat64(s.liquidity)                                                 AS swap_liquidity,
    d.day_swaps, d.day_usd, d.day_median_tick, d.day_median_liquidity
FROM priced AS s
CROSS JOIN of_the_day AS d
WHERE s.usd >= {target_usd:Float64} * (1 - {tolerance:Float64})
  AND s.usd <= {target_usd:Float64} * (1 + {tolerance:Float64})
ORDER BY s.block_timestamp, s.log_index
