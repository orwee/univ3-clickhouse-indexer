-- EVIDENCE: one pool-day hour by hour, ours against the external hourly candles.
--   {pool:String} {day:Date} {source:String}   stable_* as in 03_external_b.sql
-- The external table is a ReplacingMergeTree: FINAL. Hours the source omits count as 0 there.

WITH
    arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, {pool:String})) = 1 AS stable_is_0,
    arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, {pool:String}))      AS stable_dec,
    ours AS
    (
        SELECT toStartOfHour(block_timestamp, 'UTC') AS hour_start,
               count() AS swaps,
               sum(toFloat64(abs(if(stable_is_0, amount0, amount1)))) / pow(10, stable_dec) AS usd
        FROM raw_swaps
        WHERE pool_address = {pool:String} AND toDate(block_timestamp, 'UTC') = {day:Date}
        GROUP BY hour_start
    ),
    theirs AS
    (
        SELECT hour AS hour_start, volume_usd AS usd
        FROM external_hourly_volume FINAL
        WHERE source = {source:String} AND pool_address = {pool:String} AND toDate(hour, 'UTC') = {day:Date}
    )
SELECT
    toHour(if(o.swaps > 0, o.hour_start, t.hour_start), 'UTC') AS hour_of_day,
    o.swaps                                                   AS our_swaps,
    o.usd                                                     AS our_usd,
    t.usd                                                     AS external_usd,
    o.usd - t.usd                                             AS diff_usd
FROM ours AS o
FULL OUTER JOIN theirs AS t ON t.hour_start = o.hour_start
ORDER BY hour_of_day
-- join_use_nulls is PINNED to 0. These comparisons rely on an unmatched side being filled
-- with defaults ('' and 0). With join_use_nulls = 1 (a user profile can set it) they would
-- compare with NULL, the WHERE would drop exactly the rows that matter, and a day missing
-- from one side would read as "no differences".
SETTINGS join_use_nulls = 0
