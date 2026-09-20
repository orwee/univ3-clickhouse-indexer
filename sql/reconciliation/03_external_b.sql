-- RECONCILIATION B, external: OUR daily USD volume against the external source's,
-- per pool and UTC day, inside the window our data covers.
--
-- Our side is recomputed here from raw_swaps, without dbt: the absolute value of the
-- stablecoin leg, scaled by that token's decimals, a stablecoin taken at exactly 1 USD.
-- Which leg is the stablecoin is NOT decided in this file. It arrives as three aligned
-- arrays built from pools.yml and the single stablecoin list in dbt/dbt_project.yml:
--   {stable_pools:Array(String)}      pool addresses that have a stablecoin leg
--   {stable_is_token0:Array(UInt8)}   1 if that leg is token0, 0 if it is token1
--   {stable_decimals:Array(UInt8)}    decimals of that leg
-- A pool without a stablecoin is absent from the arrays and gets no USD volume at all.
--
-- The external table is a ReplacingMergeTree: FINAL, always.
-- Output: one row per (pool, day) present on EITHER side, with `presence` saying which.
-- `external_fetched_at` is when that candle was downloaded: a candle of the day of the download,
-- or later, was still open and is not a whole day. Neither that rule nor the thresholds are
-- applied here: the caller does, so that they stay visible parameters.

WITH
    ours AS
    (
        SELECT
            pool_address,
            toDate(toStartOfDay(block_timestamp, 'UTC'))  AS date,
            count()                                       AS swaps,
            toFloat64(sum(
                if(arrayElement({stable_is_token0:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address)) = 1,
                   abs(amount0), abs(amount1))
            )) / pow(10, any(arrayElement({stable_decimals:Array(UInt8)}, indexOf({stable_pools:Array(String)}, pool_address))))
                                                          AS volume_usd
        FROM raw_swaps
        WHERE has({stable_pools:Array(String)}, pool_address)
        GROUP BY pool_address, date
    ),
    window AS
    (
        SELECT min(date) AS first_day, max(date) AS last_day FROM ours
    ),
    theirs AS
    (
        SELECT pool_address, date, volume_usd, fetched_at
        FROM external_daily_volume FINAL
        WHERE source = {source:String}
          AND date BETWEEN (SELECT first_day FROM window) AND (SELECT last_day FROM window)
    )
SELECT
    if(o.pool_address != '', o.pool_address, t.pool_address)      AS pool_address,
    if(o.pool_address != '', o.date, t.date)                      AS date,
    multiIf(o.pool_address = '', 'only_external',
            t.pool_address = '', 'only_ours', 'both')             AS presence,
    date IN ((SELECT first_day FROM window), (SELECT last_day FROM window)) AS partial_day,
    o.swaps                                                       AS our_swaps,
    o.volume_usd                                                  AS our_volume_usd,
    t.volume_usd                                                  AS external_volume_usd,
    t.fetched_at                                                  AS external_fetched_at,
    o.volume_usd - t.volume_usd                                   AS abs_diff_usd,
    if(presence = 'both' AND t.volume_usd != 0,
       (o.volume_usd - t.volume_usd) / t.volume_usd, NULL)        AS rel_diff
FROM ours AS o
FULL OUTER JOIN theirs AS t ON t.pool_address = o.pool_address AND t.date = o.date
ORDER BY pool_address, date
-- join_use_nulls is PINNED to 0. These comparisons rely on an unmatched side being filled
-- with defaults ('' and 0). With join_use_nulls = 1 (a user profile can set it) they would
-- compare with NULL, the WHERE would drop exactly the rows that matter, and a day missing
-- from one side would read as "no differences".
SETTINGS join_use_nulls = 0
